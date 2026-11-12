const frame = document.querySelector("iframe");
const summary = document.querySelector("main");
const status = document.querySelector("#status");

function finish(event) {
    if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
    if (event.data?.type !== "krita-vnccs-finished" || typeof event.data.message !== "string") return;
    window.removeEventListener("message", finish);
    frame.remove();
    status.textContent = event.data.message;
    summary.hidden = false;
    if (event.data.applied === true) window.close();
}

window.addEventListener("message", finish);
frame.src = frame.dataset.src;
