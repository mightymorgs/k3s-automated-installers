import { BrowseViewProps } from './types'

export default function BrowseView({
  browsePath,
  mountLabel,
  entries,
  isLoading,
  error,
  onBack,
  onBrowseDir,
  onSelectPath,
  onNavigateTo,
}: BrowseViewProps) {
  const segments = browsePath.split('/').filter(Boolean)

  return (
    <div>
      <div className="flex items-center gap-1 px-3 py-2 border-b border-gray-100 bg-gray-50 text-xs flex-wrap">
        <button
          type="button"
          onClick={onBack}
          className="text-blue-500 hover:text-blue-700 flex items-center gap-1"
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Mounts
        </button>
        {mountLabel && (
          <span className="text-gray-400 mx-1">|</span>
        )}
        {mountLabel && (
          <span className="text-gray-500 font-medium">{mountLabel}</span>
        )}
        {segments.map((segment, index) => {
          const segmentPath = '/' + segments.slice(0, index + 1).join('/')
          const isLast = index === segments.length - 1
          return (
            <span key={segmentPath} className="flex items-center gap-1">
              <span className="text-gray-400">/</span>
              {isLast ? (
                <span className="text-gray-700 font-mono font-medium">{segment}</span>
              ) : (
                <button
                  type="button"
                  onClick={() => onNavigateTo(segmentPath)}
                  className="text-blue-500 hover:text-blue-700 font-mono"
                >
                  {segment}
                </button>
              )}
            </span>
          )
        })}
      </div>

      <div className="max-h-48 overflow-y-auto">
        {isLoading && <div className="px-3 py-4 text-sm text-gray-500">Loading...</div>}
        {error && <div className="px-3 py-4 text-sm text-red-600">{error.message}</div>}
        {!isLoading && !error && segments.length > 1 && (
          <button
            type="button"
            onClick={() => onNavigateTo('/' + segments.slice(0, -1).join('/'))}
            className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 flex items-center gap-2 border-b border-gray-50 text-gray-500"
          >
            <svg
              className="w-4 h-4 text-gray-400 flex-shrink-0"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            <span>..</span>
          </button>
        )}
        {!isLoading && !error && entries.length === 0 && (
          <div className="px-3 py-4 text-sm text-gray-400 italic">Empty directory</div>
        )}
        {entries.map((entry) => (
          <button
            key={entry.name}
            type="button"
            onClick={() => onBrowseDir(entry.name)}
            className="w-full text-left px-3 py-2 text-sm hover:bg-blue-50 flex items-center gap-2 border-b border-gray-50 last:border-b-0"
          >
            <svg
              className="w-4 h-4 text-yellow-500 flex-shrink-0"
              fill="currentColor"
              viewBox="0 0 20 20"
            >
              <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
            </svg>
            <span>{entry.name}</span>
          </button>
        ))}
      </div>

      <div className="px-3 py-2 border-t border-gray-100 bg-gray-50 flex justify-between items-center">
        <span className="text-xs text-gray-500 truncate mr-2">{browsePath}</span>
        <button
          type="button"
          onClick={onSelectPath}
          className="text-sm bg-green-500 text-white px-4 py-1 rounded hover:bg-green-600 transition-colors flex-shrink-0"
        >
          Select
        </button>
      </div>
    </div>
  )
}
