import { useEffect, useState } from "react";
import { listMyTodos } from "../api/compliance";
import { errorMessage } from "../api/errors";
import { readStorage, writeStorage } from "../utils/safeStorage";
import type { TodoItem } from "../types/compliance";

const STORAGE_KEY = "copernicus.todos.assignee";

/** "我的待办"：按姓名查询指派给自己的违规。姓名记在本地，换一台设备要重新填。 */
export function useTodos() {
  const [assignee, setAssigneeState] = useState(() => readStorage(STORAGE_KEY) ?? "");
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let ignore = false;
    (async () => {
      const name = assignee.trim();
      if (!name) {
        if (!ignore) setTodos([]);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const data = await listMyTodos(name);
        if (ignore) return;
        setTodos(data);
      } catch (err) {
        if (!ignore) setError(errorMessage(err, "加载待办失败"));
      } finally {
        if (!ignore) setLoading(false);
      }
    })();
    return () => {
      ignore = true;
    };
  }, [assignee, version]);

  const setAssignee = (name: string) => {
    setAssigneeState(name);
    writeStorage(STORAGE_KEY, name);
  };

  const refresh = () => setVersion((v) => v + 1);

  return { assignee, setAssignee, todos, loading, error, refresh };
}
