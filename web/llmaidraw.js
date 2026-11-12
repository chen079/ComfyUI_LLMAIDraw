import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPES = ["LLMAIDrawGPTImage", "LLMAIDrawNanoBanana2", "LLMAIDrawGrokImage", "LLMAIDrawSeadream55", "LLMAIDrawSeadream55Edit"];
const REFERENCE_NODE_TYPES = ["LLMAIDrawGPTImage", "LLMAIDrawNanoBanana2", "LLMAIDrawSeadream55Edit"];
const EXTRA_REFERENCE = /^image_\d+$/;

// Keep exactly one empty reference input after the connected ones: image, image_2, image_3, ...
function updateReferenceInputs(node) {
  for (let index = node.inputs.length - 1; index >= 0; index--) {
    if (EXTRA_REFERENCE.test(node.inputs[index].name) && node.inputs[index].link == null) {
      node.removeInput(index);
    }
  }
  const base = node.inputs.find((input) => input.name === "image");
  const label = base.localized_name ?? base.label ?? base.name;
  const extra = node.inputs.filter((input) => EXTRA_REFERENCE.test(input.name));
  extra.forEach((input, index) => {
    input.name = `image_${index + 2}`;
    input.label = `${label} ${index + 2}`;
  });
  if (base.link != null) {
    node.addInput(`image_${extra.length + 2}`, "IMAGE", { label: `${label} ${extra.length + 2}` });
  }
  node.setDirtyCanvas(true, true);
}

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
    if (!REFERENCE_NODE_TYPES.includes(nodeData.name)) {
      return;
    }
    const onConnectionsChange = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function (type, index, connected, linkInfo) {
      onConnectionsChange?.apply(this, arguments);
      // Defer so replacing a link does not remove the slot being reconnected.
      if (type === LiteGraph.INPUT && !app.configuringGraph) {
        setTimeout(() => updateReferenceInputs(this));
      }
    };
    const onConfigure = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      onConfigure?.apply(this, arguments);
      setTimeout(() => updateReferenceInputs(this));
    };
  },
});
