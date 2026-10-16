import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { ToastContainer } from "./components/shared/ToastContainer";
import { ErrorBoundary } from "./components/shared/ErrorBoundary";
import { WorkspaceSkeleton } from "./components/shared/WorkspaceSkeleton";

// 工作区依赖波形、虚拟列表等较重的库，按路由拆分以缩短首页加载
const WorkspacePage = lazy(() =>
  import("./pages/WorkspacePage").then((m) => ({ default: m.WorkspacePage })),
);
const HealthPage = lazy(() =>
  import("./pages/HealthPage").then((m) => ({ default: m.HealthPage })),
);
const RuleLibraryPage = lazy(() =>
  import("./pages/RuleLibraryPage").then((m) => ({ default: m.RuleLibraryPage })),
);
const TodosPage = lazy(() =>
  import("./pages/TodosPage").then((m) => ({ default: m.TodosPage })),
);
const AnalyticsPage = lazy(() =>
  import("./pages/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })),
);

function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <Suspense fallback={<WorkspaceSkeleton />}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/workspace/:taskId" element={<WorkspacePage />} />
            <Route path="/health" element={<HealthPage />} />
            <Route path="/rules" element={<RuleLibraryPage />} />
            <Route path="/todos" element={<TodosPage />} />
            <Route path="/analytics" element={<AnalyticsPage />} />
          </Routes>
        </Suspense>
        <ToastContainer />
      </BrowserRouter>
    </ErrorBoundary>
  );
}

export default App;
