export interface RequestError {
  response?: {
    data?: {
      message?: string;
    };
  };
  data?: {
    message?: string;
  };
  message?: string;
  errorFields?: unknown;
}

export function getErrorMessage(err: unknown, fallback = '操作失败'): string {
  if (!err) return fallback;
  if (typeof err === 'string') return err;
  const apiErr = err as {
    message?: string;
    error?: string;
    data?: { message?: string };
    response?: { data?: { message?: string } };
  };
  return (
    apiErr?.data?.message ||
    apiErr?.response?.data?.message ||
    apiErr?.message ||
    apiErr?.error ||
    fallback
  );
}
