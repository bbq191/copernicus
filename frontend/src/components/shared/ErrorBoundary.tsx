import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { ErrorAlert } from "./ErrorAlert";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/** 兜底渲染异常：避免整页白屏，并提供返回首页的出口。 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("UI render error:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4 p-8">
        <ErrorAlert message={`页面出现异常：${this.state.error.message}`} />
        <a className="btn btn-primary btn-sm" href="/">
          返回首页
        </a>
      </div>
    );
  }
}
