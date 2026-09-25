/** localStorage 在隐私模式/被禁用时会抛异常；这里统一吞掉，调用方按"没存过"处理。 */
export function readStorage(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStorage(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    // 存不下就算了：这只是便利性偏好，不影响功能
  }
}
