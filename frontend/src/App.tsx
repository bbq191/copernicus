import { BrowserRouter, Routes, Route } from "react-router-dom";
import { HomePage } from "./pages/HomePage";
import { WorkspacePage } from "./pages/WorkspacePage";
import { HealthPage } from "./pages/HealthPage";
import { ToastContainer } from "./components/shared/ToastContainer";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/workspace/:taskId" element={<WorkspacePage />} />
        <Route path="/health" element={<HealthPage />} />
      </Routes>
      <ToastContainer />
    </BrowserRouter>
  );
}

export default App;
