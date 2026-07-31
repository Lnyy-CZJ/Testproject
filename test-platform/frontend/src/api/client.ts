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
async function request(path: string, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...init.headers,
      },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new ApiError(`请求失败：HTTP ${response.status}`, response.status);
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

/** 获取数据库中启用的工具目录。 */
export async function fetchTools(): Promise<Tool[]> {
  const response = await request(`${API_PREFIX}/tools`);
  const payload = (await response.json()) as ToolListResponse;
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
  useFallback: boolean,
): Promise<boolean> {
  const path = useFallback
    ? tool.fallback_health_path
    : `${API_PREFIX}/tools/${encodeURIComponent(tool.id)}/health`;
  if (!path) {
    return false;
  }

  try {
    const response = await request(path);
    const payload = (await response.json()) as
      | PlatformToolHealthResponse
      | { status?: string };
    return useFallback
      ? payload.status === "ok"
      : payload.status === "healthy";
  } catch {
    return false;
  }
}
