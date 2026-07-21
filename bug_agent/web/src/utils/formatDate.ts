import dayjs from 'dayjs';

export function formatDateTime(value?: string | null, emptyLabel = '-'): string {
  if (!value) {
    return emptyLabel;
  }
  const d = dayjs(value);
  if (!d.isValid()) {
    return emptyLabel;
  }
  return d.format('YYYY-MM-DD HH:mm:ss');
}
