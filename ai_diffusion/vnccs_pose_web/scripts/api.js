// Server-only features (SAM 3D Body and hosted pose repositories) are unavailable here.
export const api = {
    async fetchApi() { return new Response("Requires ComfyUI", { status: 503 }); },
};
