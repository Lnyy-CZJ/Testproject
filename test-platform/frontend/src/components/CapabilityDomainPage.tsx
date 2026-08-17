import { NavLink } from "react-router-dom";

import { useToolCatalog } from "../context/ToolCatalogContext";
import { domainMeta } from "../data/capabilityCatalog";
import type { CapabilityDomainId } from "../types/tool";
import { CapabilityCard } from "./CapabilityCard";

const flowByTool: Record<string, string[]> = {
  "functional-test-agent": ["需求输入", "测试点生成", "人工 Review", "用例生成", "导出"],
  "api-test-agent": ["契约解析", "AI 用例设计", "人工确认", "接口执行", "问题分析"],
  "api-autotest": ["选择稳定接口", "准备回归数据", "执行断言", "查看报告"],
  trackevents: ["提交日志", "解析事件", "校验字段", "查看结果"],
  "log-filter": ["提交日志", "设置条件", "分析线索", "导出结果"],
  "truthy-search": ["准备样本", "执行检索", "字段对比", "生成评测报告"],
};

/** 四个能力域复用同一页面结构，仅由目录权限和领域配置驱动。 */
export function CapabilityDomainPage({ domainId }: { domainId: CapabilityDomainId }) {
  const { groups, loading, error, reloadCatalog } = useToolCatalog();
  const meta = domainMeta[domainId];
  const capabilities = groups[domainId];

  return (
    <section className="domain-page" aria-labelledby="domain-page-title">
      <header className="domain-hero">
        <p className="section-label">{meta.eyebrow}</p>
        <h1 id="domain-page-title">{meta.title}</h1>
        <p>{meta.description}</p>
      </header>
      {loading && <div className="catalog-state" role="status"><span className="loading-indicator" />正在读取该能力域的授权工具…</div>}
      {!loading && error && <div className="catalog-state catalog-state-error" role="alert"><div><strong>平台目录暂时不可用</strong><p>身份或数据服务异常，能力入口已安全关闭。</p></div><button className="secondary-button" type="button" onClick={() => void reloadCatalog()}>重新加载目录</button></div>}
      {!loading && !error && capabilities.length === 0 && <div className="catalog-state"><div><strong>当前账号没有该能力域的可见工具</strong><p>如需使用，请联系平台管理员调整工具权限。</p></div></div>}
      {!loading && !error && capabilities.length > 0 && (
        <div className="domain-capabilities">
          {capabilities.map((capability) => <article className="domain-capability" key={capability.toolId}><CapabilityCard capability={capability} /><div className="flow-panel" aria-label={`${capability.displayName}推荐流程`}><p className="section-label">推荐流程</p><ol>{(flowByTool[capability.toolId] ?? []).map((stage, index) => <li key={stage}><span>{String(index + 1).padStart(2, "0")}</span>{stage}</li>)}</ol></div></article>)}
        </div>
      )}
      {domainId === "ai-testing" && <section className="guidance-panel" aria-labelledby="guidance-title"><div><p className="section-label">推荐链路</p><h2 id="guidance-title">从探索到回归</h2></div><ol><li>API 智能测试</li><li>修复与确认</li><li>接口自动化回归</li></ol><p>这是使用建议，不传递任务数据，也不合并两个 Agent。</p></section>}
      {domainId === "automation" && <p className="domain-note">接口仍在快速变化时，可先返回 <NavLink to="/ai-testing">AI 测试</NavLink> 完成探索和问题确认；两个工具之间不传递任务 ID、文档或数据。</p>}
      <section className="platform-boundary" aria-label="平台边界"><strong>独立能力原则</strong><span>任务数据独立</span><span>任务阶段独立</span><span>业务模型独立</span><span>发布节奏独立</span></section>
    </section>
  );
}
