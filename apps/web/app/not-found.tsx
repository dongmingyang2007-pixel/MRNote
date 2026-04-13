import Link from "next/link";
import "@/styles/globals.css";

export default function RootNotFound() {
  return (
    <html lang="zh">
      <body style={{ margin: 0 }}>
        <div className="not-found-page">
          <header className="not-found-header">
            <Link href="/" className="not-found-brand">
              <span className="not-found-dot" />
              <span className="not-found-brand-name">铭润科技</span>
            </Link>
          </header>

          <main className="not-found-main">
            <div className="not-found-code-wrap" aria-hidden="true">
              <span className="not-found-code">404</span>
              <span className="not-found-scanline" />
            </div>

            <h1 className="not-found-title">页面未找到</h1>
            <p className="not-found-body">
              你访问的地址不存在，可能是链接已失效或资源已被移除。
            </p>

            <div className="not-found-actions">
              <Link href="/" className="not-found-btn-primary">
                返回首页
              </Link>
              <Link href="/app" className="not-found-btn-secondary">
                打开控制台
              </Link>
            </div>
          </main>

          <footer className="not-found-footer">
            <p>© 2026 铭润科技</p>
          </footer>
        </div>
      </body>
    </html>
  );
}
