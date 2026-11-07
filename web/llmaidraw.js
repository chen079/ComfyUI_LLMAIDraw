import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPES = ["LLMAIDrawGPTImage", "LLMAIDrawNanoBanana2", "LLMAIDrawGrokImage"];

async function refreshModels(node) {
  const profile = node.widgets.find((widget) => widget.name === "profile").value;
  const model = node.widgets.find((widget) => widget.name === "model");
  const response = await api.fetchApi("/llmaidraw/models", {
    method: "POST",
    body: JSON.stringify({ node_type: node.comfyClass, profile }),
  });
  const result = await response.json();
  if (!response.ok) {
    alert(`LLMAIDraw: ${result.error}`);
    return;
  }
  model.options.values = [...new Set([...result.models, ...model.options.values])];
  if (!result.models.includes(model.value)) {
    model.value = result.models[0];
  }
  node.setDirtyCanvas(true);
}

app.registerExtension({
  name: "LLMAIDraw.RefreshModels",
  beforeRegisterNodeDef(nodeType, nodeData) {
    if (!NODE_TYPES.includes(nodeData.name)) {
      return;
    }
    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      this.addWidget("button", "获取模型列表 / Refresh models", null, () => refreshModels(this), { serialize: false });
    };
  },
});
