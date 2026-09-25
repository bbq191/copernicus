/**
 * 工作区级别的取消范围。
 *
 * 摘要、合规审核等长耗时请求在组件卸载后仍要继续（切换标签页不该丢进度），
 * 但切换/离开任务时必须停止，否则旧任务的结果会写进新任务的 store。
 * resetWorkspaceStores 在切换任务时调用 cancelTaskWork。
 */
let controller = new AbortController();

/** 当前任务范围的信号；发起请求时取一次，回调里用 signal.aborted 判断是否已过期。 */
export function currentTaskSignal(): AbortSignal {
  return controller.signal;
}

export function cancelTaskWork(): void {
  controller.abort();
  controller = new AbortController();
}
