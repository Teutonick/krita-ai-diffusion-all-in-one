const apply = document.querySelector("#apply");
const importer = document.querySelector("#import");
const status = document.querySelector("#status");
const container = document.querySelector("#studio");
let studio, observer, healthTimer;
let finished = false;
let applying = false;

function finish(message, applied = false) {
    if (finished) return;
    finished = true;
    clearInterval(healthTimer);
    observer?.disconnect();
    try {
        studio?.dispose();
    } finally {
        window.parent.postMessage({ type: "krita-vnccs-finished", message, applied }, location.origin);
    }
}

try {
    const { PoseStudioWidget } = await import("./extensions/vnccs/vnccs_pose_studio.js");
    const initial = await (await fetch("./state")).json();
    const dataWidget = { name: "pose_data", value: "{}" };
    const node = { id: "krita_pose", widgets: [dataWidget], size: [1200, 800] };
    class KritaPoseStudio extends PoseStudioWidget {
        queueCaptureUpload() {}
        scheduleAnimationCacheUpload() {}
        autoRefreshEnabledPoseRepositories() {}
        showLibraryModal() {
            this.kritaRepository = "local_user_poses";
            super.showLibraryModal();
            const toolbar = this.libraryModal.querySelector(".vnccs-ps-library-toolbar");
            const source = document.createElement("select");
            source.setAttribute("aria-label", "Pose library source");
            source.add(new Option("Local Library", "local_user_poses"));
            source.add(new Option("VNCCS Main (online)", "miuproject"));
            source.add(new Option("General Poses (online)", "totemistyk"));
            toolbar.prepend(source);
            source.onchange = async () => {
                const previous = this.kritaRepository;
                const repo = source.value;
                source.disabled = true;
                try {
                    if (repo !== "local_user_poses") {
                        const response = await fetch("./vnccs/pose_library/remote/enable", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ repository: repo }),
                        });
                        if (!response.ok) throw new Error("Could not load the public pose catalog.");
                    }
                    if (!source.isConnected) return;
                    this.kritaRepository = repo;
                    this.librarySelectedName = null;
                    this.libraryActiveCategory = "All";
                    await this.refreshLibrary(false);
                } catch (error) {
                    this.kritaRepository = previous;
                    source.value = previous;
                    this.showMessage(error.message, true);
                } finally {
                    source.disabled = false;
                }
            };
        }
        async refreshLibrary(forceFull = false) {
            if (forceFull || !this.kritaRepository || this.kritaRepository === "local_user_poses") {
                return super.refreshLibrary(forceFull);
            }
            const repo = this.kritaRepository;
            const modal = this.libraryModal;
            const token = this._libraryRefreshToken = (this._libraryRefreshToken || 0) + 1;
            const response = await fetch("./vnccs/pose_library/list?repository=" + encodeURIComponent(repo));
            const data = await response.json();
            if (!response.ok || !Array.isArray(data.poses)) throw new Error("Could not load poses.");
            if (token !== this._libraryRefreshToken || this.libraryModal !== modal) return;
            this.libraryPoses = data.poses;
            this.renderLibrary();
        }

    }
    studio = new KritaPoseStudio(node);
    container.append(studio.container);
    observer = new ResizeObserver(() => studio.resize());
    observer.observe(container);
    let healthPending = false;
    healthTimer = setInterval(async () => {
        if (healthPending || applying || finished) return;
        healthPending = true;
        const request = new AbortController();
        const timeout = setTimeout(() => request.abort(), 2000);
        try {
            const response = await fetch("./health", { signal: request.signal });
            if (!response.ok && !applying) finish("Pose Studio was closed in Krita.");
        } catch {
            if (!applying) finish("Pose Studio was closed in Krita.");
        } finally {
            clearTimeout(timeout);
            healthPending = false;
        }
    }, 1000);

    async function restore(pose) {
        dataWidget.value = JSON.stringify(pose);
        studio.loadFromNode();
        await studio.loadModel(true, false);
        await studio.awaitReadyForCompositeCapture();
        if (studio._poseDataRestoreError) throw new Error(studio._poseDataRestoreError);
        if (!studio.viewer?.isInitialized()) throw new Error("WebGL mannequin initialization failed.");
        studio.resize();
    }

    await studio._viewerInitPromise;
    await restore(initial.pose_data || {
        export: {
            view_width: initial.width, view_height: initial.height,
            skin_type: "dummy_white", bg_color: [0, 0, 0], hand_controls_v2: true,
        },
    });
    status.textContent = "Ready";
    apply.disabled = importer.disabled = false;

    importer.onchange = async () => {
        if (!importer.files.length) return;
        apply.disabled = importer.disabled = true;
        const previous = JSON.parse(dataWidget.value);
        try {
            const file = importer.files[0];
            if (file.size > 20 * 1024 * 1024) throw new Error("JSON file is too large.");
            const data = JSON.parse(await file.text());
            const poseNode = data.nodes?.find(node => node.type === "VNCCS_PoseStudio");
            const pose = poseNode ? JSON.parse(poseNode.widgets_values[0]) : data.pose_data || data;
            if (!Array.isArray(pose.poses) && !Array.isArray(pose.characters)) {
                throw new Error("No VNCCS pose state found in this JSON.");
            }
            await restore(pose);
            status.textContent = "Pose loaded";
        } catch (error) {
            await restore(previous);
            status.textContent = error.message;
        } finally {
            apply.disabled = importer.disabled = false;
            importer.value = "";
        }
    };

    apply.onclick = async () => {
        applying = true;
        apply.disabled = importer.disabled = true;
        status.textContent = "Rendering pose…";
        try {
            if (studio.isAnimationMode()) throw new Error("Switch to Image mode to use one pose.");
            const { view_width, view_height } = studio.exportParams;
            if (Math.max(view_width, view_height) > 2048) {
                throw new Error("Set capture dimensions to 2048 pixels or less.");
            }
            await studio.awaitReadyForCompositeCapture();
            studio.syncToNode(false, { skipCapture: true, skipCaptureUpload: true });
            studio.syncToNode(true, { skipCaptureUpload: true, executionCapture: true });
            const capture = studio.poseCaptures[studio.activeTab];
            if (!capture?.startsWith("data:image/png;base64,")) {
                throw new Error("VNCCS did not render the active pose.");
            }
            const response = await fetch("./apply", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ pose_data: JSON.parse(dataWidget.value), capture }),
            });
            if (!response.ok) throw new Error("Krita could not accept the pose.");
            finish("Pose sent. Return to Krita.", true);
        } catch (error) {
            status.textContent = error.message;
            apply.disabled = importer.disabled = false;
        } finally {
            applying = false;
        }
    };
} catch (error) {
    console.error(error);
    finish(error.message || "Pose Studio could not open.");
}
