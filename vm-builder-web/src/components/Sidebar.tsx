import { NavLink } from 'react-router-dom'

interface NavItem {
  to: string
  label: string
  subtitle: string
}

export type { NavItem }

export default function Sidebar({ items }: { items: NavItem[] }) {
  return (
    <aside className="w-60 bg-white border-r border-gray-200 min-h-screen flex flex-col">
      <div className="px-4 py-4 border-b border-gray-200">
        <NavLink to="/" className="text-lg font-semibold text-gray-900">
          vm-builder
        </NavLink>
      </div>
      <nav className="flex-1 px-2 py-4 space-y-1">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) =>
              `block px-3 py-2 rounded-md transition-colors ${
                isActive
                  ? 'bg-blue-50 border-l-2 border-blue-600'
                  : 'hover:bg-gray-50'
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span className={`text-sm font-medium block ${isActive ? 'text-blue-700' : 'text-gray-700'}`}>
                  {item.label}
                </span>
                <span className={`text-xs block mt-0.5 ${isActive ? 'text-blue-500' : 'text-gray-400'}`}>
                  {item.subtitle}
                </span>
              </>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}
