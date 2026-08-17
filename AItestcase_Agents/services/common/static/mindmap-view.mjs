import { flattenTree } from "./mindmap-domain.mjs";

/**
 * Mind Elixir 的受控适配层。
 *
 * 画布永远不作为业务数据来源。库的写操作先被 before guard 拦截，
 * 再交给上层 Domain Command；上层完成后以平面 JSON 重新投影刷新。
 */
export class MindmapView {
  constructor(container, { onSelect, onMove, onRename, onError, maxVisible = 500 } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.onMove = onMove || (() => {});
    this.onRename = onRename || (() => {});
    this.onError = onError || (() => {});
    this.maxVisible = maxVisible;
    this.instance = null;
    this.didInitialFit = false;
    this.metaById = new Map();
    this.handleClick = (event) => {
      const topic = event.target.closest?.("[data-nodeid]");
      const meta = this.resolveTopicMeta(topic);
      if (meta) this.onSelect(meta);
    };
    this.handleKeydown = (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      const topic = event.target.closest?.("[data-nodeid]");
      const meta = this.resolveTopicMeta(topic);
      if (meta) {
        event.preventDefault();
        this.onSelect(meta);
      }
    };
    this.handleDoubleClick = (event) => {
      /** Mind Elixir 的手势编辑在受控刷新模式下不稳定，因此使用同位置原生输入框提交领域命令。 */
      const topic = event.target.closest?.("[data-nodeid]");
      const meta = this.resolveTopicMeta(topic);
      if (!topic || !meta) return;
      event.preventDefault(); event.stopPropagation();
      this.startInlineEdit(topic, meta);
    };
    this.container.addEventListener("click", this.handleClick);
    this.container.addEventListener("keydown", this.handleKeydown);
    this.container.addEventListener("dblclick", this.handleDoubleClick, true);
  }

  render(data) {
    const visible = flattenTree(data.nodeData).length;
    if (visible > this.maxVisible) {
      this.onError(`当前需要渲染 ${visible} 个节点，请先折叠分组或缩小筛选范围`);
      return false;
    }
    const ctor = globalThis.MindElixir?.default;
    if (!ctor) {
      this.onError("脑图组件加载失败，可切换到只读表格或关闭 V2 回退旧界面");
      return false;
    }
    if (!this.instance) this.instance = this.createInstance(ctor);
    try {
      this.metaById = new Map();
      flattenTree(data.nodeData).forEach((node) => {
        this.metaById.set(node.id, node.meta);
        this.metaById.set(`me${node.id}`, node.meta);
      });
      if (this.instance.nodeData) this.instance.refresh(data);
      else this.instance.init(data);
      this.instance.clearHistory?.();
      if (!this.didInitialFit) {
        this.didInitialFit = true;
        // Mind Elixir 在下一帧后仍可能处于字体和连线测量阶段，短延迟后再适应画布。
        setTimeout(() => this.instance?.scaleFit?.(), 80);
      }
      setTimeout(() => this.enableKeyboardTopics(), 0);
      return true;
    } catch (_error) {
      this.onError("脑图渲染失败，业务草稿未发生变化");
      return false;
    }
  }

  createInstance(ctor) {
    const interceptMove = (placement) => async (from, to) => {
      const sources = Array.isArray(from) ? from : [from];
      const sourceMeta = sources.map((item) => item?.nodeObj?.meta || item?.nodeObj?.metadata || this.resolveTopicMeta(item)).filter(Boolean);
      const targetMeta = to?.nodeObj?.meta || to?.nodeObj?.metadata || this.resolveTopicMeta(to);
      if (sourceMeta.length && targetMeta) this.onMove({ sources: sourceMeta, target: targetMeta, placement });
      return false;
    };
    const deny = () => false;
    const instance = new ctor({
      el: this.container,
      direction: ctor.RIGHT,
      editable: true,
      contextMenu: false,
      toolBar: false,
      keypress: false,
      allowUndo: false,
      compact: true,
      overflowHidden: true,
      markdown: undefined,
      before: {
        addChild: deny,
        insertSibling: deny,
        insertParent: deny,
        removeNodes: deny,
        copyNodes: deny,
        reshapeNode: deny,
        moveNodeIn: interceptMove("inside"),
        moveNodeBefore: interceptMove("before"),
        moveNodeAfter: interceptMove("after"),
      },
      theme: {
        name: "Test Platform",
        type: "light",
        palette: ["#0071e3", "#3784d6", "#4c7fb8", "#55789d", "#6e6e73", "#18794e"],
        cssVar: {
          "--main-color": "#1d1d1f",
          "--main-bgcolor": "#ffffff",
          "--main-border": "1px solid rgba(0,0,0,.14)",
          "--color": "#1d1d1f",
          "--bgcolor": "#ffffff",
          "--selected": "#0071e3",
          "--accent-color": "#0071e3",
          "--root-color": "#ffffff",
          "--root-bgcolor": "#1d1d1f",
          "--root-border-color": "#1d1d1f",
          "--root-radius": "10px",
          "--main-radius": "9px",
          "--topic-padding": "7px 10px",
          "--node-gap-x": "28px",
          "--node-gap-y": "8px",
          "--main-gap-x": "58px",
          "--main-gap-y": "34px",
          "--map-padding": "36px",
        },
      },
    });
    instance.bus.addListener("selectNodes", (nodes) => {
      // selectNodes 直接返回 NodeObj；移动守卫收到的才是带 nodeObj 的 Topic 元素。
      const node = nodes?.[nodes.length - 1];
      const selected = node?.meta || node?.metadata;
      if (selected) this.onSelect(selected);
    });
    instance.bus.addListener("operation", (operation) => {
      /** 双击编辑结束时只提交领域命令；随后由平面 JSON 重新投影，避免脑图库成为事实源。 */
      if (operation?.name !== "finishEdit") return;
      const meta = operation.obj?.meta || operation.obj?.metadata || this.metaById.get(operation.obj?.id);
      if (meta) this.onRename(meta, String(operation.obj?.topic || ""), String(operation.origin || ""));
    });
    return instance;
  }

  resolveTopicMeta(topic) {
    /** 5.14.0 的 Topic DOM 仅暴露 data-nodeid，因此用投影期建立的只读映射定位业务元数据。 */
    const nodeId = topic?.dataset?.nodeid || topic?.getAttribute?.("data-nodeid");
    return nodeId ? this.metaById.get(nodeId) || this.metaById.get(nodeId.replace(/^me/, "")) : null;
  }

  enableKeyboardTopics() {
    /** 脑图库关闭内建快捷键后，补充最小语义与 Enter/Space 选择能力。 */
    this.container.querySelectorAll("[data-nodeid]").forEach((topic) => {
      topic.tabIndex = 0;
      topic.setAttribute("role", "treeitem");
    });
  }

  startInlineEdit(topic, meta) {
    /** 在节点原位置编辑纯文本，确认后仍由上层回写平面 JSON。 */
    this.container.querySelector(".mindmap-inline-editor")?.remove();
    const bounds = topic.getBoundingClientRect();
    const host = this.container.getBoundingClientRect();
    const input = document.createElement("input");
    input.className = "mindmap-inline-editor";
    input.value = topic.querySelector(".text")?.textContent?.trim() || topic.textContent?.trim() || "";
    input.style.left = `${bounds.left - host.left}px`;
    input.style.top = `${bounds.top - host.top}px`;
    input.style.width = `${Math.max(160, bounds.width)}px`;
    let finished = false;
    const finish = (commit) => {
      if (finished || !input.isConnected) return;
      finished = true;
      const value = input.value.trim(); input.remove();
      if (commit && value) this.onRename(meta, value);
    };
    input.addEventListener("keydown", (keyEvent) => {
      keyEvent.stopPropagation();
      if (keyEvent.key === "Enter") { keyEvent.preventDefault(); finish(true); }
      if (keyEvent.key === "Escape") { keyEvent.preventDefault(); finish(false); }
    });
    input.addEventListener("blur", () => finish(true), { once: true });
    this.container.append(input); input.focus(); input.select();
  }

  focus(nodeId) {
    const target = this.instance?.findEle?.(nodeId);
    if (!target) return;
    this.instance.selectNode(target);
    this.instance.scrollIntoView(target, true);
  }

  fit() {
    this.instance?.scaleFit?.();
  }

  center() {
    this.instance?.toCenter?.();
  }

  expandAll(expanded) {
    if (this.instance?.root) this.instance.expandNodeAll(this.instance.root, expanded);
  }

  destroy() {
    this.instance?.destroy?.();
    this.instance = null;
    this.container.removeEventListener("click", this.handleClick);
    this.container.removeEventListener("keydown", this.handleKeydown);
    this.container.removeEventListener("dblclick", this.handleDoubleClick, true);
    this.container.replaceChildren();
  }
}
