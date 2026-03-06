import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

interface ToastItem {
  id: number
  type: 'error' | 'success' | 'warning'
  message: string
  hint?: string
}

interface ToastContextValue {
  success: (message: string) => void
  error: (message: string, opts?: { hint?: string }) => void
  warning: (message: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}

let nextId = 0
const MAX_TOASTS = 5

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  const remove = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const add = useCallback(
    (type: ToastItem['type'], message: string, hint?: string) => {
      const id = nextId++
      setToasts((prev) => {
        const next = [...prev, { id, type, message, hint }]
        return next.length > MAX_TOASTS ? next.slice(next.length - MAX_TOASTS) : next
      })
      if (type !== 'error') {
        const ms = type === 'warning' ? 6000 : 4000
        setTimeout(() => remove(id), ms)
      }
    },
    [remove],
  )

  const value: ToastContextValue = {
    success: (msg) => add('success', msg),
    error: (msg, opts) => add('error', msg, opts?.hint),
    warning: (msg) => add('warning', msg),
  }

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed top-4 right-4 z-50 flex flex-col gap-2 w-96">
        {toasts.map((t) => (
          <ToastMessage key={t.id} toast={t} onDismiss={() => remove(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

const TYPE_STYLES: Record<ToastItem['type'], string> = {
  error: 'bg-red-50 border-red-400 text-red-800',
  success: 'bg-green-50 border-green-400 text-green-800',
  warning: 'bg-yellow-50 border-yellow-400 text-yellow-800',
}

function ToastMessage({ toast, onDismiss }: { toast: ToastItem; onDismiss: () => void }) {
  return (
    <div
      className={`border-l-4 rounded-r-lg shadow-lg p-4 animate-slide-in ${TYPE_STYLES[toast.type]}`}
      role="alert"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{toast.message}</p>
          {toast.hint && (
            <p className="mt-1 text-xs opacity-75">{toast.hint}</p>
          )}
        </div>
        <button
          onClick={onDismiss}
          className="shrink-0 text-current opacity-50 hover:opacity-100"
          aria-label="Dismiss"
        >
          ✕
        </button>
      </div>
    </div>
  )
}
