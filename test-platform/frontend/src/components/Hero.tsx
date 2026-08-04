/** 展示平台定位和当前接入规模。 */
export function Hero({ toolCount }: { toolCount: number }) {
  return (
    <section className="hero" aria-labelledby="page-title">
      <p className="section-label">测试工程工作台</p>
      <h1 id="page-title">从一个入口开始测试。</h1>
      <p className="hero-copy">
        快速进入埋点校验、日志分析与检索评测，执行任务，理解结果并处理失败。
      </p>
      <p className="platform-summary">
        当前已接入 <strong>{toolCount}</strong> 个独立工具
      </p>
    </section>
  );
}
