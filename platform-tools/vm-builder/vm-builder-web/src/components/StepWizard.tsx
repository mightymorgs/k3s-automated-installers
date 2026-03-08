import { useState } from 'react'

/**
 * Generic multi-step form wizard container.
 * Renders numbered step indicators, navigation buttons, and
 * the content panel for the currently active step.
 *
 * Per-step canProceed: Each step can optionally define its own
 * canProceed boolean. When present, it takes precedence over the
 * global canProceed prop for that step.
 */
export default function StepWizard({
  steps,
  onComplete,
  canProceed = true,
}: {
  steps: { label: string; content: React.ReactNode; canProceed?: boolean }[]
  onComplete: () => void
  canProceed?: boolean
}) {
  const [current, setCurrent] = useState(0)
  const isLast = current === steps.length - 1

  // Per-step canProceed takes precedence over the global prop
  const currentCanProceed =
    steps[current].canProceed !== undefined
      ? steps[current].canProceed
      : canProceed

  return (
    <div>
      {/* Step indicators */}
      <div className="flex items-center gap-2 mb-8">
        {steps.map((step, i) => (
          <div key={i} className="flex items-center gap-2">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-medium ${
                i === current
                  ? 'bg-blue-600 text-white'
                  : i < current
                    ? 'bg-blue-100 text-blue-700'
                    : 'bg-gray-200 text-gray-500'
              }`}
            >
              {i + 1}
            </div>
            <span
              className={`text-sm ${
                i === current
                  ? 'font-semibold text-gray-900'
                  : 'text-gray-500'
              }`}
            >
              {step.label}
            </span>
            {i < steps.length - 1 && (
              <div className="w-8 h-px bg-gray-300 mx-1" />
            )}
          </div>
        ))}
      </div>

      {/* Current step content */}
      <div className="mb-8">{steps[current].content}</div>

      {/* Navigation buttons */}
      <div className="flex justify-between">
        <button
          onClick={() => setCurrent((c) => c - 1)}
          disabled={current === 0}
          className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          Previous
        </button>
        {isLast ? (
          <button
            onClick={onComplete}
            disabled={!currentCanProceed}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Complete
          </button>
        ) : (
          <button
            onClick={() => setCurrent((c) => c + 1)}
            disabled={!currentCanProceed}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        )}
      </div>
    </div>
  )
}
