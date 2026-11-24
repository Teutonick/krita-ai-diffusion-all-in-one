# pyright: reportMissingImports=false, reportAttributeAccessIssue=false
# This module runs in the managed ComfyUI interpreter.
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch
from comfy import model_management
from folder_paths import models_dir
from PIL import Image
from torchvision.models.detection import ssdlite320_mobilenet_v3_large
from torchvision.ops import box_area, box_iou

from .anygles import camera_prompt
from .nodes import _pil_to_tensor, _tensor_to_pil
from .sam3d_normal import (
    Sam3DNormalGenerator,
    _project,
    _render_in_subprocess,
    _rotate_elevation,
    _rotate_yaw,
)

assets = Path(models_dir) / "krita_pov"
required_assets = (
    "model.ckpt",
    "model_config.yaml",
    "assets/mhr_model.pt",
    "moge.pt",
    "detector.pth",
)


def _framing_pivot(points, pivot, focal, width, height):
    frame = np.array([width, height], dtype=np.float32)
    projection = _project(points, np.zeros(3, dtype=np.float32), focal, width, height)
    low, high = projection.min(0), projection.max(0)
    if np.all(low >= 0) and np.all(high <= frame):
        return pivot

    visible_low = np.maximum(low, 0)
    visible_high = np.minimum(high, frame)
    if np.any(visible_low >= visible_high):
        return pivot
    center = (visible_low + visible_high) * 0.5
    anchor = pivot.copy()
    anchor[:, :2] = (center - frame * 0.5) * anchor[:, 2:3] / focal
    return anchor


def person_boxes(predictions):
    person = (predictions["labels"] == 1) & (predictions["scores"] >= 0.25)
    boxes = predictions["boxes"][person]
    scores = predictions["scores"][person]
    selected = scores >= 0.55
    overlap = box_iou(boxes, boxes)
    areas = box_area(boxes)
    heights = boxes[:, 3] - boxes[:, 1]
    centers = (boxes[:, 0] + boxes[:, 2]) * 0.5
    for index in torch.where(selected)[0].tolist():
        width = boxes[index, 2] - boxes[index, 0]
        intersection = overlap[index] * (areas[index] + areas) / (1 + overlap[index])
        within = (
            (areas < areas[index] * 0.85)
            & (intersection >= areas * 0.74)
            & (heights > heights[index] * 0.65)
        )
        candidates = torch.where(within)[0].tolist()
        pairs = [
            (a, b)
            for a in candidates
            for b in candidates
            if a < b and overlap[a, b] < 0.5 and abs(centers[a] - centers[b]) >= width * 0.25
        ]
        if pairs:
            a, b = max(pairs, key=lambda pair: float(scores[pair[0]] + scores[pair[1]]))
            selected[index] = False
            selected[a] = selected[b] = True
    return boxes[selected]


class KritaPOVGeometry:
    CATEGORY = "Krita/Make POVs"
    RETURN_TYPES = ("KRITA_POV_GEOMETRY",)
    FUNCTION = "reconstruct"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"image": ("IMAGE",)}}

    def reconstruct(self, image):
        rgb = _tensor_to_pil(image)
        return (self._reconstruct(rgb.size, rgb.tobytes()),)

    @staticmethod
    @lru_cache(maxsize=1)
    @torch.inference_mode()
    def _reconstruct(size, pixels):
        rgb = Image.frombytes("RGB", size, pixels)
        detector = ssdlite320_mobilenet_v3_large(
            weights=None, weights_backbone=None, nms_thresh=0.7
        )
        detector.load_state_dict(
            torch.load(assets / "detector.pth", map_location="cpu", weights_only=True)
        )
        detector.eval()
        tensor = torch.from_numpy(np.array(rgb)).movedim(-1, 0).float() / 255.0
        predictions = detector([tensor])[0]
        boxes = person_boxes(predictions)
        if len(boxes) > 2:
            raise ValueError(f"Make POVs needs one or two clear people; detected {len(boxes)}.")
        # A cropped or stylized portrait can miss the person detector and still fit SAM's mesh.
        if len(boxes) <= 1:
            boxes = torch.tensor([[0, 0, rgb.width, rgb.height]], dtype=torch.float32)
        else:
            padding = (boxes[:, 2:] - boxes[:, :2]) * 0.06
            limit = torch.tensor([rgb.width, rgb.height])
            boxes = torch.cat(
                (
                    (boxes[:, :2] - padding).clamp(min=0),
                    torch.minimum(boxes[:, 2:] + padding, limit),
                ),
                dim=1,
            )

        model_management.unload_all_models()
        model_management.soft_empty_cache(force=True)
        generator = Sam3DNormalGenerator(
            Path(__file__).parent,
            assets / "model.ckpt",
            assets / "assets/mhr_model.pt",
            moge_model=str(assets / "moge.pt"),
            device=str(model_management.get_torch_device()),
        )
        try:
            people = generator.estimator.process_one_image(
                np.asarray(rgb), bboxes=boxes.numpy(), inference_type="body"
            )
            if len(people) != len(boxes):
                raise ValueError(
                    "Make POVs could not reconstruct the subject geometry from this image."
                )
            points, faces, pelvis, focal = [], [], [], []
            offset = 0
            for person in people:
                camera = np.asarray(person["pred_cam_t"], dtype=np.float32)
                vertices = np.asarray(person["pred_vertices"], dtype=np.float32) + camera
                joints = np.asarray(person["pred_keypoints_3d"], dtype=np.float32)
                points.append(vertices)
                faces.append(np.asarray(generator.estimator.faces) + offset)
                pelvis.append((joints[9] + joints[10]) * 0.5 + camera)
                focal.append(float(np.asarray(person["focal_length"]).item()))
                offset += len(vertices)
            geometry = (
                np.concatenate(points),
                np.concatenate(faces),
                np.repeat(np.mean(pelvis, axis=0)[None, :], 11, axis=0),
                float(np.mean(focal)),
                rgb.size,
                len(people),
            )
            return geometry
        finally:
            generator.close()


class KritaPOVNormal:
    CATEGORY = "Krita/Make POVs"
    RETURN_TYPES = ("IMAGE", "STRING")
    FUNCTION = "render"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "geometry": ("KRITA_POV_GEOMETRY",),
                "azimuth": ("INT", {"min": -180, "max": 180}),
                "elevation": ("FLOAT", {"min": -60.0, "max": 60.0}),
                "distance": ("FLOAT", {"min": 0.6, "max": 1.8}),
            },
            "optional": {"subject_context": ("STRING", {"default": "", "multiline": True})},
        }

    def render(self, geometry, azimuth, elevation, distance, subject_context=""):
        points, faces, pivot, focal, (width, height), count = geometry
        pivot = _framing_pivot(points, pivot, focal, width, height)
        vertices = _rotate_elevation(_rotate_yaw(points, pivot, azimuth), pivot, elevation)
        camera = np.array([0, 0, pivot[0, 2] * (distance - 1)], dtype=np.float32)
        normal = _render_in_subprocess(vertices, faces, camera, focal, width, height, 1.0, (0, 0))
        instructions = (
            "Preserve the two distinct subjects and their relative placement."
            if count == 2
            else "Preserve the same subject."
        )
        instructions += (
            " Match the source design, silhouette, surfaces, materials and colors. "
            "Keep the same scene, lighting and background. Change only the viewpoint. "
            "Preserve the source shot size, camera distance and lens perspective. "
            "Keep the source crop, including any body parts or features that extend out of frame. "
            "Keep unspecified areas visually consistent with the source."
        )
        details = "\n".join(filter(None, (subject_context.strip(), instructions)))
        return _pil_to_tensor(normal), camera_prompt(azimuth, elevation, distance, details)


node_mappings = (
    {"KritaPOVGeometry": KritaPOVGeometry, "KritaPOVNormal": KritaPOVNormal}
    if all((assets / name).is_file() for name in required_assets)
    else {}
)
