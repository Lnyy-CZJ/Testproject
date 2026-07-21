import axios, { type AxiosRequestConfig, type AxiosResponse, type Method } from 'axios';
import { appStorage } from '../utils/storage';

/**
 * 获取 API 基础地址。
 *
 * 开发环境默认使用相对地址，由 Vite 代理转发到 Python 服务；部署时可通过
 * VITE_API_BASE_URL 指向网关或 Python API，避免在前端代码中写死服务地址。
 */
export const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '');

/**
 * 拼接 API 相对路径。
 *
 * 参数说明:
 *   path: 以 `/` 开头的 API 相对路径。
 * 返回值:
 *   string: 可直接用于 fetch、EventSource 的完整 API 地址。
 */
export function getApiUrl(path: string): string {
  return `${apiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
}

const SESSION_EXPIRED_MESSAGES = new Set([
  'missing authorization header',
  'invalid authorization format',
  'invalid token',
  '未登录',
  'Authentication required',
]);

const shouldClearAuthSession = (error: {
  response?: {
    status?: number;
    data?: {
      message?: string;
      error?: string;
    };
  };
}) => {
  if (error.response?.status !== 401) {
    return false;
  }

  const message = error.response?.data?.message?.trim();
  const fallbackError = error.response?.data?.error?.trim();
  const reason = message || fallbackError || '';
  return SESSION_EXPIRED_MESSAGES.has(reason);
};

const axiosInstance = axios.create({
  baseURL: apiBaseUrl,
  timeout: 15000,
});

axiosInstance.interceptors.request.use((config) => {
  const token = appStorage.getToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

const COMMA_FIELDS = new Set(['agentTypes', 'tags', 'channels']);

function transformCommaFields(obj: unknown): unknown {
  if (!obj || typeof obj !== 'object') return obj;
  if (Array.isArray(obj)) return obj.map(transformCommaFields);
  const record = obj as Record<string, unknown>;
  const next: Record<string, unknown> = {};
  for (const key of Object.keys(record)) {
    const val = record[key];
    if (COMMA_FIELDS.has(key) && typeof val === 'string') {
      next[key] = val.split(',').map((s) => s.trim()).filter(Boolean);
    } else if (val && typeof val === 'object') {
      next[key] = transformCommaFields(val);
    } else {
      next[key] = val;
    }
  }
  return next;
}

const unwrapApiResponse = (response: AxiosResponse): ApiResult => {
    const data = transformCommaFields(response.data);
    if (data && typeof data === 'object' && 'code' in data) {
      const result = data as { code: number; message?: string };
      if (result.code !== 0) {
        // 抛出业务错误，使 axios 以 rejected Promise 交给调用方处理。
        throw {
          status: response.status,
          data,
          message: result.message || `请求失败 (code: ${result.code})`,
        };
      }
      return data as ApiResult;
    }
    // Non-standard response: wrap as { code: 0, data: originalData }
    return { code: 0, data };
};

axiosInstance.interceptors.response.use(
  // Axios 类型默认要求拦截器返回 AxiosResponse；本项目请求层约定直接返回 ApiResult。
  unwrapApiResponse as unknown as (response: AxiosResponse) => AxiosResponse,
  (error) => {
    if (shouldClearAuthSession(error)) {
      appStorage.clear();
      if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/register')) {
        window.location.assign('/login');
        return Promise.reject({
          status: error.response?.status,
          data: error.response?.data,
          message: error.response?.data?.message || error.message,
        });
      }
    }
    return Promise.reject({
      status: error.response?.status,
      data: error.response?.data,
      message: error.response?.data?.message || error.message,
    });
  }
);

export interface ApiResult<T = unknown> {
  code: number;
  data?: T;
  message?: string;
}

function request<T = unknown>(method: Method, url: string, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return axiosInstance({ method, url, ...config }) as Promise<ApiResult<T>>;
}

export function get<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return request<T>('get', url, config);
}

export function post<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return request<T>('post', url, { data, ...config });
}

export function put<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return request<T>('put', url, { data, ...config });
}

export function patch<T = unknown>(url: string, data?: unknown, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return request<T>('patch', url, { data, ...config });
}

export function del<T = unknown>(url: string, config?: AxiosRequestConfig): Promise<ApiResult<T>> {
  return request<T>('delete', url, config);
}

export default { get, post, put, patch, delete: del };
