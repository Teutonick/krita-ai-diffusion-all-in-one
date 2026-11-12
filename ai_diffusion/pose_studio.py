from __future__ import annotations

import json
from dataclasses import dataclass, field
from itertools import pairwise
from math import cos, isfinite, pi, sin

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPolygonF, QQuaternion, QVector3D

from .image import Extent, Image

# Parent, rest position, and radius for each joint. Coordinates are in body units.
rig = (
    (-1, (0.0, 0.0, 0.0), 0.14),  # pelvis
    (0, (0.0, 0.38, 0.0), 0.19),  # chest
    (1, (0.0, 0.54, 0.0), 0.06),  # neck
    (2, (0.0, 0.68, 0.015), 0.10),  # head
    (1, (-0.22, 0.41, 0.0), 0.078),
    (4, (-0.43, 0.15, 0.02), 0.047),
    (5, (-0.55, -0.08, 0.09), 0.034),
    (6, (-0.58, -0.17, 0.11), 0.043),
    (1, (0.22, 0.41, 0.0), 0.078),
    (8, (0.43, 0.15, 0.02), 0.047),
    (9, (0.55, -0.08, 0.09), 0.034),
    (10, (0.58, -0.17, 0.11), 0.043),
    (0, (-0.12, -0.08, 0.0), 0.10),
    (12, (-0.15, -0.46, 0.035), 0.065),
    (13, (-0.17, -0.84, 0.0), 0.043),
    (14, (-0.17, -0.88, 0.13), 0.054),
    (0, (0.12, -0.08, 0.0), 0.10),
    (16, (0.15, -0.46, 0.035), 0.065),
    (17, (0.17, -0.84, 0.0), 0.043),
    (18, (0.17, -0.88, 0.13), 0.054),
)


@dataclass
class PoseScene:
    joints: list[QVector3D] = field(default_factory=lambda: [QVector3D(*p) for _, p, _ in rig])
    yaw: float = 15.0
    pitch: float = 5.0
    zoom: float = 1.0
    pan_x: float = 0.0
    pan_y: float = 0.0

    @staticmethod
    def load(value: str) -> PoseScene:
        if value:
            try:
                state = json.loads(value)
                joints = state["joints"]
                camera = state["camera"]
                if len(joints) != len(rig) or any(len(p) != 3 for p in joints) or len(camera) != 5:
                    return PoseScene()
                if not all(isfinite(v) for p in joints for v in p) or not all(
                    isfinite(v) for v in camera
                ):
                    return PoseScene()
                if not 0.3 <= camera[2] <= 3.0:
                    return PoseScene()
                return PoseScene([QVector3D(*p) for p in joints], *camera)
            except (TypeError, ValueError, KeyError, OverflowError):
                pass
        return PoseScene()

    def save(self):
        return json.dumps(
            {
                "joints": [[p.x(), p.y(), p.z()] for p in self.joints],
                "camera": [self.yaw, self.pitch, self.zoom, self.pan_x, self.pan_y],
            },
            separators=(",", ":"),
        )

    @property
    def camera(self):
        return QQuaternion.fromEulerAngles(self.pitch, self.yaw, 0.0)

    def scale(self, depth: float, frame: QRectF):
        return (
            min(frame.height() / 2.0, frame.width() / 1.55)
            * self.zoom
            * (4.0 / max(0.8, 4.0 - depth))
        )

    def project(self, frame: QRectF):
        camera = self.camera
        origin = frame.center() + QPointF(self.pan_x * frame.width(), self.pan_y * frame.height())
        result: list[tuple[QPointF, float, float]] = []
        for joint in self.joints:
            p = camera.rotatedVector(joint - QVector3D(0, -0.09, 0))
            scale = self.scale(p.z(), frame)
            result.append((origin + QPointF(p.x() * scale, -p.y() * scale), p.z(), scale))
        return result

    def move(self, index: int, delta: QPointF, frame: QRectF, depth_only: bool):
        scale = self.project(frame)[index][2]
        offset = QVector3D(0, 0, -delta.y()) if depth_only else QVector3D(delta.x(), -delta.y(), 0)
        offset = self.camera.conjugated().rotatedVector(offset / scale)
        if index == 0:
            self.joints = [p + offset for p in self.joints]
            return
        pivot = self.joints[rig[index][0]]
        before = self.joints[index] - pivot
        after = before + offset
        if after.lengthSquared() < 1e-8:
            return
        rotation = QQuaternion.rotationTo(before, after)
        branch = {index}
        for i in range(index, len(rig)):
            if i == index or rig[i][0] in branch:
                branch.add(i)
                self.joints[i] = pivot + rotation.rotatedVector(self.joints[i] - pivot)

    def _surface(self, frame: QRectF, preview: bool):
        camera = self.camera
        origin = frame.center() + QPointF(self.pan_x * frame.width(), self.pan_y * frame.height())
        light = QVector3D(-0.45, 0.7, 0.9).normalized()
        faces: list[tuple[float, int, QPolygonF]] = []
        segments = 16 if preview else 28
        subdivisions = (0.0, 0.5) if preview else (0.0, 0.25, 0.5, 0.75)
        circle = [(cos(2 * pi * i / segments), sin(2 * pi * i / segments)) for i in range(segments)]

        def screen(v: QVector3D):
            scale = self.scale(v.z(), frame)
            return origin + QPointF(v.x() * scale, -v.y() * scale)

        def part(
            a: QVector3D,
            b: QVector3D,
            front: QVector3D,
            profile: tuple[tuple[float, float, float], ...],
        ):
            axis = (b - a).normalized()
            side = QVector3D.crossProduct(axis, front).normalized()
            if side.lengthSquared() < 0.01:
                side = QVector3D.crossProduct(axis, QVector3D(1, 0, 0)).normalized()
            if side.lengthSquared() < 0.01:
                return
            front = QVector3D.crossProduct(side, axis).normalized()

            def smooth_radius(values: tuple[float, ...], i: int, t: float):
                a, b = values[i], values[i + 1]
                m0 = (b - values[max(0, i - 1)]) / 2
                m1 = (values[min(len(values) - 1, i + 2)] - a) / 2
                return max(
                    0.001,
                    a + t * (m0 + t * (3 * (b - a) - 2 * m0 - m1 + t * (2 * (a - b) + m0 + m1))),
                )

            widths, depths = tuple(r[1] for r in profile), tuple(r[2] for r in profile)
            profile = tuple(
                (a[0] + (b[0] - a[0]) * t, smooth_radius(widths, i, t), smooth_radius(depths, i, t))
                for i, (a, b) in enumerate(pairwise(profile))
                for t in subdivisions
            ) + (profile[-1],)
            centers = [
                camera.rotatedVector(a + (b - a) * t + QVector3D(0, 0.09, 0)) for t, _, _ in profile
            ]
            x, z = camera.rotatedVector(side), camera.rotatedVector(front)
            rings = [
                [center + x * (c * width) + z * (s * depth) for c, s in circle]
                for center, (_, width, depth) in zip(centers, profile)
            ]
            for k, (lower, upper) in enumerate(pairwise(rings)):
                for i in range(segments):
                    j = (i + 1) % segments
                    vertices = (lower[i], lower[j], upper[j], upper[i])
                    center = (vertices[0] + vertices[1] + vertices[2] + vertices[3]) / 4
                    normal = QVector3D.crossProduct(
                        vertices[2] - vertices[0], vertices[3] - vertices[1]
                    ).normalized()
                    radial = center - (centers[k] + centers[k + 1]) / 2
                    if QVector3D.dotProduct(normal, radial) < 0:
                        normal = -normal
                    if QVector3D.dotProduct(normal, QVector3D(0, 0, 4) - center) <= 0:
                        continue
                    shade = round(95 + 144 * max(0.0, QVector3D.dotProduct(normal, light)))
                    faces.append((center.z(), shade, QPolygonF([screen(p) for p in vertices])))

        p = self.joints
        up = (p[1] - p[0]).normalized()
        across = (p[8] - p[4]).normalized()
        front = QVector3D.crossProduct(across, up).normalized()
        if front.lengthSquared() < 0.01:
            front = QVector3D(0, 0, 1)
        # A continuous torso profile: hips, waist, rib cage, shoulders, neck.
        part(
            p[0],
            p[1],
            front,
            (
                (-0.35, 0.002, 0.002),
                (-0.28, 0.116, 0.076),
                (-0.12, 0.157, 0.102),
                (0.12, 0.155, 0.103),
                (0.39, 0.112, 0.076),
                (0.62, 0.143, 0.091),
                (0.88, 0.183, 0.104),
                (1.08, 0.191, 0.086),
                (1.28, 0.092, 0.060),
                (1.41, 0.002, 0.002),
            ),
        )
        part(p[1], p[2], front, ((0.1, 0.070, 0.058), (0.68, 0.043, 0.041), (1.24, 0.045, 0.039)))
        head_up = (p[3] - p[2]).normalized()
        head_front = QVector3D.crossProduct(across, head_up).normalized()
        if head_front.lengthSquared() < 0.01:
            head_front = front
        part(
            p[2],
            p[3],
            head_front,
            (
                (0.28, 0.002, 0.002),
                (0.45, 0.039, 0.039),
                (0.65, 0.053, 0.052),
                (0.91, 0.064, 0.066),
                (1.15, 0.066, 0.063),
                (1.38, 0.046, 0.050),
                (1.50, 0.002, 0.002),
            ),
        )
        nose = p[2] + (p[3] - p[2]) * 0.88 + head_front * 0.060
        part(
            nose - head_up * 0.025,
            nose + head_up * 0.023,
            head_front,
            (
                (0.0, 0.002, 0.002),
                (0.22, 0.013, 0.022),
                (0.6, 0.009, 0.017),
                (1.0, 0.002, 0.002),
            ),
        )

        def limb(a: int, b: int, widths: tuple[float, float, float], depth: float):
            profile = tuple(
                (t, r, r * depth)
                for t, r in zip(
                    (-0.24, -0.1, 0.18, 0.60, 1.04, 1.23),
                    (0.002, widths[0] * 0.83, *widths, 0.002),
                )
            )
            part(p[a], p[b], front, profile)

        for shoulder, hip in ((4, 12), (8, 16)):
            limb(shoulder, shoulder + 1, (0.064, 0.052, 0.038), 0.88)
            limb(shoulder + 1, shoulder + 2, (0.043, 0.034, 0.023), 0.83)
            limb(shoulder + 2, shoulder + 3, (0.032, 0.029, 0.018), 0.58)
            limb(hip, hip + 1, (0.096, 0.074, 0.048), 0.95)
            limb(hip + 1, hip + 2, (0.058, 0.043, 0.028), 0.91)
            limb(hip + 2, hip + 3, (0.042, 0.043, 0.029), 0.65)
        return sorted(faces, key=lambda face: face[0])

    def draw(self, painter: QPainter, frame: QRectF, handles=False):
        painter.save()
        painter.setClipRect(frame)
        painter.fillRect(frame, Qt.GlobalColor.black)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        for _, shade, polygon in self._surface(frame, preview=handles):
            painter.setBrush(QColor(shade, shade, shade))
            painter.drawPolygon(polygon)
        if handles:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for i, (p, _, _) in enumerate(self.project(frame)):
                painter.setBrush(QColor("#ffd57b" if i < 4 else "#78dfd9"))
                painter.drawEllipse(p, 5.0, 5.0)
        painter.restore()

    def render(self, extent: Extent) -> Image:
        scale = min(1.0, 1024 / extent.longest_side)
        width, height = max(1, round(extent.width * scale)), max(1, round(extent.height * scale))
        image = QImage(width, height, QImage.Format.Format_RGB32)
        painter = QPainter(image)
        self.draw(painter, QRectF(0, 0, width, height))
        painter.end()
        return Image(image)
