import type { ReactNode } from 'react';

type ShellNavigationEntry =
  | {
      type?: 'item';
      key: string;
      icon: ReactNode;
      label: ReactNode;
      active?: boolean;
      onClick: () => void;
    }
  | {
      type: 'divider';
      key: string;
    };

interface ShellNavigationProps {
  items: ShellNavigationEntry[];
}

export default function ShellNavigation({ items }: ShellNavigationProps) {
  return (
    <div className="shell-navigation">
      <div className="shell-rail">
        {items.map((item) => {
          if (item.type === 'divider') {
            return <div key={item.key} className="shell-navigation__divider" />;
          }

          return (
            <button
              key={item.key}
              type="button"
              className={`shell-rail__item ${item.active ? 'is-active' : ''}`}
              onClick={item.onClick}
            >
              <span className="shell-rail__icon">{item.icon}</span>
              <span className="shell-rail__text">
                <span className="shell-rail__title">{item.label}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
