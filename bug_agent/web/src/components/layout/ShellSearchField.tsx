interface ShellSearchFieldProps {
  ariaLabel: string;
  placeholder: string;
}

export default function ShellSearchField({
  ariaLabel,
  placeholder,
}: ShellSearchFieldProps) {
  return (
    <label className="topbar-search shell-search-field" aria-label={ariaLabel}>
      <svg style={{ width: 16, height: 16, color: '#94a3b8' }} fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input type="text" placeholder={placeholder} />
    </label>
  );
}
