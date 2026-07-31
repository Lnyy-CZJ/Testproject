/** 展示明确不在第一轮实现、但已经规划的后续平台能力。 */
export function Roadmap() {
  return (
    <section className="roadmap" aria-labelledby="roadmap-title">
      <div>
        <p className="section-label">后续能力</p>
        <h2 id="roadmap-title">为完整测试流程持续扩展</h2>
        <p>后续将逐步接入统一任务记录、结果汇总与团队协作能力。</p>
      </div>
      <div className="roadmap-items" aria-label="计划接入能力">
        <span>测试 Agent</span>
        <span>接口自动化</span>
        <span>用例管理</span>
        <span>报告中心</span>
      </div>
    </section>
  );
}
