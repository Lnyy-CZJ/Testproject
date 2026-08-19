import { flattenTree } from "./mindmap-domain.mjs?v=20260819-free-review-4";

/**
 * Mind Elixir 的受控适配层。
 *
 * 画布永远不作为业务数据来源。库的写操作先被 before guard 拦截，
 * 再交给上层 Domain Command；上层完成后以平面 JSON 重新投影刷新。
 */
export class MindmapView {
  constructor(container, { onSelect, onMove, onCanMove, onRename, onAdd, onBoxSelect, onContext, onScale, onError, maxVisible = 500 } = {}) {
    this.container = container;
    this.onSelect = onSelect || (() => {});
    this.onMove = onMove || (() => {});
    this.onCanMove = onCanMove || (() => true);
    this.onRename = onRename || (() => {});
    this.onAdd = onAdd || (() => {});
    this.onBoxSelect = onBoxSelect || (() => {});
    this.onContext = onContext || (() => {});
    this.onScale = onScale || (() => {});
    this.onError = onError || (() => {});
    this.maxVisible = maxVisible;
    this.instance = null;
    this.didInitialFit = false;
    this.metaById = new Map();
    this.expandedById = new Map();
    this.panState = null;
    this.boxState = null;
    this.nodeDrag = null;
    this.detailRevealTimer = null;
    this.handleClick = (event) => {
      if (event.target.closest?.("me-epd")) {
        const expander = event.target.closest("me-epd");
        const topic = expander.previousElementSibling;
        const initial = this.expanderState?.element === expander ? this.expanderState.expanded : topic?.nodeObj?.expanded !== false;
        // 部分浏览器下库的 pointerup 目标会漂移；仅在库未切换时执行一次兜底，避免双重反转。
        if (topic && (topic.nodeObj?.expanded !== false) === initial) this.instance?.expandNode?.(topic, !initial);
        this.expanderState = null; this.captureExpandedState(); this.decorateTopics(); this.drawMinimap();
        return;
      }
      const add = event.target.closest?.(".mindmap-node-add");
      if (add) {
        event.preventDefault(); event.stopPropagation();
        const meta = this.resolveTopicMeta(add.closest("[data-nodeid]"));
        if (meta) this.onAdd(meta, "child");
        return;
      }
      const topic = event.target.closest?.("[data-nodeid]");
      const meta = this.resolveTopicMeta(topic);
      if (meta) {
        this.onSelect(meta, { toggle: event.metaKey || event.ctrlKey });
        // 鼠标能点击到的节点已经可见，此处只更新选择与详情。主动居中会在
        // 双击的两次 click 之间移动目标，导致原位编辑无法稳定触发。
        clearTimeout(this.detailRevealTimer);
        this.detailRevealTimer = setTimeout(() => this.onSelect(meta, { revealDetails: true }), 600);
      }
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
      const topic = event.target.closest?.("[data-nodeid]");
      const meta = this.resolveTopicMeta(topic);
      if (!meta) return;
      event.preventDefault(); event.stopPropagation();
      clearTimeout(this.detailRevealTimer); this.detailRevealTimer = null;
      this.nodeDrag = null;
      this.onSelect(meta, { editing: true });
      this.edit(topic?.dataset?.nodeid?.replace(/^me/, ""));
    };
    this.handlePointerDown = (event) => this.pointerDown(event);
    this.handlePointerMove = (event) => this.pointerMove(event);
    this.handlePointerUp = (event) => this.pointerUp(event);
    this.handleContextMenu = (event) => {
      const topic = event.target.closest?.("[data-nodeid]");
      const meta = this.resolveTopicMeta(topic);
      if (!meta) return;
      event.preventDefault();
      this.onContext(meta, { x: event.clientX, y: event.clientY });
    };
    this.container.addEventListener("click", this.handleClick);
    this.container.addEventListener("keydown", this.handleKeydown);
    this.container.addEventListener("dblclick", this.handleDoubleClick, true);
    this.container.addEventListener("pointerdown", this.handlePointerDown, true);
    this.container.addEventListener("pointermove", this.handlePointerMove, true);
    this.container.addEventListener("pointerup", this.handlePointerUp, true);
    this.container.addEventListener("pointercancel", this.handlePointerUp, true);
    this.container.addEventListener("contextmenu", this.handleContextMenu);
  }

  render(data) {
    this.captureExpandedState();
    this.applyExpandedState(data.nodeData);
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
      const allNodes = [];
      const collect = (node) => { allNodes.push(node); node.children?.forEach(collect); };
      collect(data.nodeData);
      allNodes.forEach((node) => {
        this.metaById.set(node.id, node.meta);
        this.metaById.set(`me${node.id}`, node.meta);
      });
      if (this.instance.nodeData) this.instance.refresh(data);
      else this.instance.init(data);
      this.instance.clearHistory?.();
      if (!this.didInitialFit) {
        this.didInitialFit = true;
        // Mind Elixir 在下一帧后仍可能处于字体和连线测量阶段，短延迟后再适应画布。
        setTimeout(() => {
          this.instance?.scaleFit?.();
          if (Number(this.instance?.scaleVal || 1) < 0.7) this.instance?.scale?.(0.7);
          this.instance?.toCenter?.(); this.onScale(Number(this.instance?.scaleVal || 1)); this.drawMinimap();
        }, 80);
      }
      setTimeout(() => this.enableKeyboardTopics(), 0);
      setTimeout(() => { this.decorateTopics(); this.drawMinimap(); }, 0);
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
      scaleSensitivity: 0.05,
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
    instance.bus.addListener("scale", (scale) => this.onScale(Number(scale) || 1));
    return instance;
  }

  captureExpandedState() {
    /** 展开状态只属于浏览器视图；刷新平面 JSON 时按稳定节点 ID 恢复。 */
    const visit = (node) => {
      if (!node) return;
      if (Array.isArray(node.children) && node.children.length) this.expandedById.set(node.id, node.expanded !== false);
      node.children?.forEach(visit);
    };
    visit(this.instance?.nodeData);
  }

  applyExpandedState(node) {
    if (!node) return;
    if (this.expandedById.has(node.id)) node.expanded = this.expandedById.get(node.id);
    node.children?.forEach((child) => this.applyExpandedState(child));
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

  decorateTopics() {
    /** 节点按钮和状态标签均使用 textContent，避免把业务文本作为 HTML 注入。 */
    this.container.querySelectorAll("[data-nodeid]").forEach((topic) => {
      const meta = this.resolveTopicMeta(topic);
      if (!meta || meta.kind === "root") return;
      if (!topic.querySelector(".mindmap-node-add")) {
        const add = document.createElement("button");
        add.type = "button"; add.className = "mindmap-node-add"; add.textContent = "+";
        add.setAttribute("aria-label", `在${topic.textContent?.trim() || "当前节点"}下新增`);
        topic.append(add);
      }
      const status = meta.statusLabel;
      if (status && !topic.querySelector(".mindmap-node-status")) {
        const badge = document.createElement("span"); badge.className = "mindmap-node-status"; badge.textContent = status; topic.append(badge);
      }
    });
  }

  pointerDown(event) {
    const expander = event.target.closest?.("me-epd");
    if (expander) {
      this.expanderState = { element: expander, expanded: expander.previousElementSibling?.nodeObj?.expanded !== false };
      return;
    }
    const topic = event.target.closest?.("me-tpc");
    if (event.button === 0 && topic && !event.target.closest?.("button,input,textarea,select,.mindmap-inline-editor")) {
      const meta = this.resolveTopicMeta(topic);
      if (meta?.kind !== "root") {
        this.nodeDrag = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, topic, meta, dragging: false, target: null, placement: "inside" };
      }
      return;
    }
    if (event.button !== 0 || event.target.closest?.("button,input,textarea,select,.mindmap-inline-editor")) return;
    if (event.shiftKey) {
      const rect = document.createElement("div"); rect.className = "mindmap-box-selection"; this.container.append(rect);
      this.boxState = { pointerId: event.pointerId, startX: event.clientX, startY: event.clientY, rect };
    } else {
      this.panState = { pointerId: event.pointerId, x: event.clientX, y: event.clientY };
      this.container.classList.add("is-panning");
    }
    event.currentTarget.setPointerCapture?.(event.pointerId);
    event.preventDefault();
  }

  pointerMove(event) {
    if (this.nodeDrag?.pointerId === event.pointerId) {
      const distance = Math.hypot(event.clientX - this.nodeDrag.startX, event.clientY - this.nodeDrag.startY);
      if (!this.nodeDrag.dragging && distance > 5) {
        this.nodeDrag.dragging = true; this.nodeDrag.topic.classList.add("is-domain-dragging");
        // 仅在确认进入拖动后捕获指针；按下即捕获会把 click/dblclick 重定向到画布，令选择和原生编辑失效。
        this.container.setPointerCapture?.(event.pointerId);
        const ghost = document.createElement("div"); ghost.className = "mindmap-domain-ghost"; ghost.textContent = this.nodeDrag.topic.querySelector(".text")?.textContent || "移动节点"; this.container.append(ghost); this.nodeDrag.ghost = ghost;
      }
      if (!this.nodeDrag.dragging) return;
      event.preventDefault(); event.stopPropagation();
      const host = this.container.getBoundingClientRect();
      Object.assign(this.nodeDrag.ghost.style, { left: `${event.clientX - host.left + 12}px`, top: `${event.clientY - host.top + 12}px` });
      this.nodeDrag.target?.classList.remove("mindmap-drop-target", "mindmap-drop-invalid", "is-before", "is-after", "is-inside");
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest?.("me-tpc");
      if (target && target !== this.nodeDrag.topic) {
        const bounds = target.getBoundingClientRect(); const ratio = (event.clientY - bounds.top) / Math.max(1, bounds.height);
        this.nodeDrag.placement = ratio < 0.25 ? "before" : ratio > 0.75 ? "after" : "inside";
        this.nodeDrag.target = target;
        const targetMeta = this.resolveTopicMeta(target);
        this.nodeDrag.valid = Boolean(targetMeta && this.onCanMove({ sources: [this.nodeDrag.meta], target: targetMeta, placement: this.nodeDrag.placement }));
        target.classList.add(this.nodeDrag.valid ? "mindmap-drop-target" : "mindmap-drop-invalid", `is-${this.nodeDrag.placement}`);
      } else this.nodeDrag.target = null;
      return;
    }
    if (this.panState?.pointerId === event.pointerId) {
      const dx = event.clientX - this.panState.x; const dy = event.clientY - this.panState.y;
      this.panState.x = event.clientX; this.panState.y = event.clientY;
      this.instance?.move?.(dx, dy);
      this.drawMinimap();
      return;
    }
    if (this.boxState?.pointerId !== event.pointerId) return;
    const host = this.container.getBoundingClientRect();
    const left = Math.min(this.boxState.startX, event.clientX) - host.left;
    const top = Math.min(this.boxState.startY, event.clientY) - host.top;
    Object.assign(this.boxState.rect.style, { left: `${left}px`, top: `${top}px`, width: `${Math.abs(event.clientX - this.boxState.startX)}px`, height: `${Math.abs(event.clientY - this.boxState.startY)}px` });
  }

  pointerUp(event) {
    if (this.nodeDrag?.pointerId === event.pointerId) {
      const drag = this.nodeDrag; this.nodeDrag = null;
      drag.topic.classList.remove("is-domain-dragging"); drag.target?.classList.remove("mindmap-drop-target", "mindmap-drop-invalid", "is-before", "is-after", "is-inside"); drag.ghost?.remove();
      if (drag.dragging) {
        event.preventDefault(); event.stopPropagation();
        const targetMeta = this.resolveTopicMeta(drag.target);
        if (targetMeta && drag.valid) this.onMove({ sources: [drag.meta], target: targetMeta, placement: drag.placement });
        else this.onError(targetMeta ? "该节点层级不允许放置，数据未发生变化" : "未找到可放置的目标节点，数据未发生变化");
      }
      if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
      if (drag.dragging) return;
    }
    if (this.panState?.pointerId === event.pointerId) {
      this.panState = null; this.container.classList.remove("is-panning");
    }
    if (this.boxState?.pointerId === event.pointerId) {
      const selection = this.boxState.rect.getBoundingClientRect();
      const metas = [...this.container.querySelectorAll("[data-nodeid]")].filter((topic) => {
        const bounds = topic.getBoundingClientRect();
        return bounds.right >= selection.left && bounds.left <= selection.right && bounds.bottom >= selection.top && bounds.top <= selection.bottom;
      }).map((topic) => this.resolveTopicMeta(topic)).filter((meta) => meta?.kind !== "root");
      this.boxState.rect.remove(); this.boxState = null; this.onBoxSelect(metas);
    }
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  }

  focus(nodeId) {
    const target = this.reveal(nodeId);
    if (!target) return;
    this.instance.selectNode(target);
    this.instance.scrollIntoView(target, true);
  }

  ensureVisible(topic) {
    /** 仅在节点超出安全可视区时居中，避免普通选择造成画布反复跳动。 */
    if (!topic) return;
    const host = this.container.getBoundingClientRect();
    const bounds = topic.getBoundingClientRect();
    const marginX = Math.min(120, host.width * 0.15);
    const marginY = Math.min(90, host.height * 0.15);
    if (bounds.left < host.left + marginX || bounds.right > host.right - marginX
      || bounds.top < host.top + marginY || bounds.bottom > host.bottom - marginY) {
      this.instance?.scrollIntoView?.(topic, true);
    }
  }

  markSelected(keys = new Set()) {
    this.container.querySelectorAll("[data-nodeid]").forEach((topic) => {
      const meta = this.resolveTopicMeta(topic);
      topic.classList.toggle("domain-selected", Boolean(meta?.uiKey && keys.has(meta.uiKey)));
    });
  }

  find(query, offset = 0) {
    const needle = String(query || "").trim().toLocaleLowerCase();
    this.container.querySelectorAll("[data-nodeid]").forEach((topic) => topic.classList.remove("search-match"));
    if (!needle) return null;
    const matches = [...this.container.querySelectorAll("[data-nodeid]")].filter((topic) => topic.textContent.toLocaleLowerCase().includes(needle));
    const target = matches[((offset % matches.length) + matches.length) % matches.length];
    if (target) { this.instance?.selectNode?.(target); this.instance?.scrollIntoView?.(target, true); }
    matches.forEach((topic) => topic.classList.add("search-match"));
    return this.resolveTopicMeta(target);
  }

  edit(nodeId) {
    const target = this.reveal(nodeId);
    if (!target) return;
    const meta = this.resolveTopicMeta(target);
    if (!meta) return;
    // 优先使用脑图库编辑器；5.14.0 对部分折叠后恢复的子节点不会创建输入框，
    // 下一事件循环检测失败后启用同一领域提交入口的轻量兜底编辑器。
    this.instance?.beginEdit?.(target);
    setTimeout(() => {
      if (typeof Element !== "undefined" && target instanceof Element
        && !this.container.querySelector("#input-box,me-textarea,.mindmap-inline-editor")) this.openFallbackEditor(target, meta);
    }, 0);
  }

  openFallbackEditor(target, meta) {
    this.container.querySelector(".mindmap-inline-editor")?.remove();
    const host = this.container.getBoundingClientRect();
    const bounds = target.getBoundingClientRect();
    const editor = document.createElement("textarea");
    editor.className = "mindmap-inline-editor";
    editor.value = String(meta.label ?? "");
    editor.setAttribute("aria-label", "编辑脑图节点");
    Object.assign(editor.style, {
      position: "absolute", zIndex: "20", left: `${bounds.left - host.left}px`, top: `${bounds.top - host.top}px`,
      width: `${Math.max(180, Math.min(520, bounds.width + 80))}px`, minHeight: `${Math.max(38, bounds.height)}px`,
    });
    let finished = false;
    const finish = (save) => {
      if (finished) return;
      finished = true;
      const value = editor.value.trim(); editor.remove();
      if (save && value && value !== String(meta.label ?? "")) this.onRename(meta, value, String(meta.label ?? ""));
    };
    editor.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Escape") { event.preventDefault(); finish(false); }
      else if (event.key === "Enter" && (!meta.detailField || event.ctrlKey || event.metaKey)) { event.preventDefault(); finish(true); }
    });
    editor.addEventListener("blur", () => finish(true));
    this.container.append(editor); editor.focus(); editor.select();
  }

  reveal(nodeId) {
    /** 新节点可能位于自动折叠分支；先展开父链，再定位，避免 findEle 抛出未捕获异常。 */
    if (!nodeId || !this.instance) return null;
    let target = null;
    try { target = this.instance.findEle?.(nodeId); } catch (_error) { /* 继续按数据父链展开。 */ }
    if (target) return target;
    const node = this.instance.getObjById?.(nodeId, this.instance.nodeData);
    if (!node) return null;
    for (let parent = node.parent; parent; parent = parent.parent) { parent.expanded = true; this.expandedById.set(parent.id, true); }
    this.instance.refresh?.(); this.decorateTopics(); this.drawMinimap();
    try { return this.instance.findEle?.(nodeId) || null; } catch (_error) { return null; }
  }

  fit() {
    this.instance?.scaleFit?.();
  }

  zoomBy(delta) {
    /** 在画布中心按固定步长缩放，并遵守脑图库配置的上下限。 */
    if (!this.instance?.scale) return;
    const minimum = Number(this.instance.scaleMin ?? 0.2);
    const maximum = Number(this.instance.scaleMax ?? 2.5);
    const current = Number(this.instance.scaleVal || 1);
    const next = Math.min(maximum, Math.max(minimum, Math.round((current + delta) * 100) / 100));
    this.instance.scale(next);
    this.onScale(next);
  }

  center() {
    this.instance?.toCenter?.();
  }

  expandAll(expanded) {
    const root = this.instance?.findEle?.(this.instance?.nodeData?.id);
    if (!root) return;
    if (expanded) this.instance.expandNodeAll(root, true);
    else {
      (this.instance.nodeData.children || []).forEach((child) => {
        const topic = this.instance.findEle?.(child.id);
        if (topic) this.instance.expandNodeAll(topic, false);
      });
      root.nodeObj.expanded = true;
    }
    this.captureExpandedState();
    this.decorateTopics(); this.drawMinimap();
  }

  toggle(nodeId) {
    const target = this.instance?.findEle?.(nodeId);
    if (!target) return;
    const expanded = target.nodeObj?.expanded !== false;
    this.instance.expandNode(target, !expanded);
    this.captureExpandedState();
  }

  expand(nodeId, expandChildren = false) {
    /** 选中用例时展开详情分支；其他节点仍只展开自身，避免一次渲染过多内容。 */
    const target = this.reveal(nodeId);
    if (target?.nodeObj?.expanded === false) {
      this.instance?.expandNode?.(target, true);
    }
    if (expandChildren) (target?.nodeObj?.children || []).forEach((child) => {
      const childTopic = this.reveal(child.id);
      // Mind Elixir 对未显式设置 expanded 的新详情分组按收起处理，因此仅 true 才视为已展开。
      if (childTopic?.nodeObj?.expanded !== true) this.instance?.expandNode?.(childTopic, true);
    });
    this.captureExpandedState(); this.decorateTopics(); this.drawMinimap();
  }

  async fullscreen() {
    if (document.fullscreenElement === this.container) await document.exitFullscreen();
    else await this.container.requestFullscreen?.();
  }

  focusBranch(nodeId) {
    if (this.instance?.isFocusMode) {
      this.instance.cancelFocus?.(); this.decorateTopics(); this.drawMinimap(); return;
    }
    const target = this.instance?.findEle?.(nodeId);
    if (target?.nodeObj?.parent) {
      this.instance.focusNode?.(target); this.decorateTopics(); this.drawMinimap();
    }
  }

  navigate(nodeId, direction) {
    const topics = [...this.container.querySelectorAll("[data-nodeid]")].filter((item) => item.offsetParent !== null);
    const current = topics.findIndex((item) => (item.dataset.nodeid || "").replace(/^me/, "") === nodeId);
    const index = Math.min(topics.length - 1, Math.max(0, current + direction));
    const target = topics[index];
    if (!target) return null;
    target.focus(); this.instance?.selectNode?.(target); this.instance?.scrollIntoView?.(target, true);
    return this.resolveTopicMeta(target);
  }

  drawMinimap() {
    let canvas = this.container.querySelector(".mindmap-minimap");
    if (!canvas) {
      canvas = document.createElement("canvas"); canvas.className = "mindmap-minimap"; canvas.width = 180; canvas.height = 110;
      canvas.setAttribute("aria-label", "脑图小地图"); this.container.append(canvas);
      canvas.addEventListener("click", (event) => {
        if (!this.minimapPoints?.length) return;
        const bounds = canvas.getBoundingClientRect(); const x = (event.clientX - bounds.left) * canvas.width / bounds.width; const y = (event.clientY - bounds.top) * canvas.height / bounds.height;
        const closest = this.minimapPoints.reduce((best, item) => !best || Math.hypot(item.x - x, item.y - y) < Math.hypot(best.x - x, best.y - y) ? item : best, null);
        if (closest) this.focus(closest.nodeId);
      });
    }
    const context = canvas.getContext?.("2d"); const topics = [...this.container.querySelectorAll("[data-nodeid]")];
    if (!context || !topics.length) return;
    const host = this.container.getBoundingClientRect();
    const boxes = topics.map((topic) => topic.getBoundingClientRect());
    const minX = Math.min(...boxes.map((box) => box.left)); const minY = Math.min(...boxes.map((box) => box.top));
    const maxX = Math.max(...boxes.map((box) => box.right)); const maxY = Math.max(...boxes.map((box) => box.bottom));
    const scale = Math.min(170 / Math.max(1, maxX - minX), 100 / Math.max(1, maxY - minY));
    context.clearRect(0, 0, canvas.width, canvas.height); context.fillStyle = "#f5f5f7"; context.fillRect(0, 0, canvas.width, canvas.height);
    context.fillStyle = "#6e6e73";
    this.minimapPoints = boxes.map((box, index) => ({ x: 5 + (box.left + box.width / 2 - minX) * scale, y: 5 + (box.top + box.height / 2 - minY) * scale, nodeId: (topics[index].dataset.nodeid || "").replace(/^me/, "") }));
    boxes.forEach((box) => context.fillRect(5 + (box.left - minX) * scale, 5 + (box.top - minY) * scale, Math.max(2, box.width * scale), 2));
    context.strokeStyle = "#0071e3"; context.lineWidth = 2;
    context.strokeRect(5 + (host.left - minX) * scale, 5 + (host.top - minY) * scale, Math.min(170, host.width * scale), Math.min(100, host.height * scale));
  }

  destroy() {
    clearTimeout(this.detailRevealTimer);
    this.instance?.destroy?.();
    this.instance = null;
    this.container.removeEventListener("click", this.handleClick);
    this.container.removeEventListener("keydown", this.handleKeydown);
    this.container.removeEventListener("dblclick", this.handleDoubleClick, true);
    this.container.removeEventListener("pointerdown", this.handlePointerDown, true);
    this.container.removeEventListener("pointermove", this.handlePointerMove, true);
    this.container.removeEventListener("pointerup", this.handlePointerUp, true);
    this.container.removeEventListener("pointercancel", this.handlePointerUp, true);
    this.container.removeEventListener("contextmenu", this.handleContextMenu);
    this.container.replaceChildren();
  }
}
