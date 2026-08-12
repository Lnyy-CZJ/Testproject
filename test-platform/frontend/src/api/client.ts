import type {
  PlatformToolHealthResponse,
  Tool,
  ToolListResponse,
} from "../types/tool";

const API_PREFIX = "/api/v1";
const REQUEST_TIMEOUT_MS = 3000;

/** 平台 API 请求失败时使用的统一错误。 */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status?: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/**
 * 发送带超时控制的同源请求。
 *
 * 参数说明:
 *   path: 以 / 开头的完整同源路径。
 *   init: 标准 fetch 请求配置。
 *
 * 返回值:
 *   成功响应对象。
 *
 * 异常说明:
 *   超时、网络错误或非 2xx 响应统一转换为 ApiError，调用方据此启用降级。
 */
function csrfToken(): string | undefined {
  const prefix = "tp_csrf=";
  return document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix))
    ?.slice(prefix.length);
}

/** 发送统一同源请求；写操作自动携带双提交 CSRF Header。 */
export async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const method = (init.method ?? "GET").toUpperCase();
    const csrf = !["GET", "HEAD", "OPTIONS"].includes(method) ? csrfToken() : undefined;
    const response = await fetch(path, {
      ...init,
      credentials: "same-origin",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(csrf ? { "X-CSRF-Token": decodeURIComponent(csrf) } : {}),
        ...init.headers,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      const payload = (await response.clone().json().catch(() => null)) as
        | { message?: string; code?: string }
        | null;
      throw new ApiError(
        payload?.message ?? `请求失败：HTTP ${response.status}`,
        response.status,
        payload?.code,
      );
    }
    return response;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("请求超时");
    }
    throw new ApiError("平台服务暂时不可用");
  } finally {
    window.clearTimeout(timeoutId);
  }
}

/** 请求并解析 JSON；所有平台页面共享相同错误和安全策略。 */
export async function apiJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await request(`${API_PREFIX}${path}`, init);
  return (await response.json()) as T;
}

/** 获取数据库中启用的工具目录。 */
export async function fetchTools(): Promise<Tool[]> {
  const payload = await apiJson<ToolListResponse>("/tools");
  if (!Array.isArray(payload.items)) {
    throw new ApiError("工具目录响应格式错误");
  }
  return payload.items;
}

/**
 * 获取单个工具状态。
 *
 * 参数说明:
 *   tool: 当前工具。
 *   useFallback: 是否绕过平台 API，直接检查已有工具公开健康地址。
 *
 * 返回值:
 *   工具正常返回 true；上游异常或响应格式不匹配返回 false。
 *
 * 异常处理:
 *   健康检查本身失败时返回 false，不向页面抛出异常，避免一个工具中断全部检查。
 */
export async function fetchToolHealth(
  tool: Tool,
  _useFallback = false,
): Promise<boolean> {
  try {
    const payload = await apiJson<PlatformToolHealthResponse>(
      `/tools/${encodeURIComponent(tool.id)}/health`,
    );
    return payload.status === "healthy";
  } catch {
    return false;
  }
}
