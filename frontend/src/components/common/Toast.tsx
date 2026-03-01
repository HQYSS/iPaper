import { X, CheckCircle, AlertCircle, Info } from 'lucide-react'
import { useToastStore } from '../../stores/toastStore'
import { cn } from '../../lib/utils'

export function ToastContainer() {
  const { toasts, removeToast } = useToastStore()

  if (toasts.length === 0) return null

  return (
    <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={cn(
            'flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg min-w-[300px] max-w-[400px]',
            'animate-in slide-in-from-right-full duration-300',
            {
              'bg-green-50 text-green-800 border border-green-200': toast.type === 'success',
              'bg-red-50 text-red-800 border border-red-200': toast.type === 'error',
              'bg-blue-50 text-blue-800 border border-blue-200': toast.type === 'info',
            }
          )}
        >
          {toast.type === 'success' && <CheckCircle className="w-5 h-5 flex-shrink-0" />}
          {toast.type === 'error' && <AlertCircle className="w-5 h-5 flex-shrink-0" />}
          {toast.type === 'info' && <Info className="w-5 h-5 flex-shrink-0" />}
          <p className="flex-1 text-sm">{toast.message}</p>
          <button
            onClick={() => removeToast(toast.id)}
            className="p-1 rounded hover:bg-black/10 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      ))}
    </div>
  )
}


