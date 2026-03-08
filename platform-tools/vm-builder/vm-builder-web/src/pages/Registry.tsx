import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

/** Map category names to Tailwind color classes for badge styling. */
const CATEGORY_COLORS: Record<string, string> = {
  infrastructure: 'bg-blue-100 text-blue-800',
  monitoring: 'bg-green-100 text-green-800',
  media: 'bg-purple-100 text-purple-800',
  security: 'bg-red-100 text-red-800',
  storage: 'bg-yellow-100 text-yellow-800',
  networking: 'bg-cyan-100 text-cyan-800',
  database: 'bg-orange-100 text-orange-800',
  identity: 'bg-pink-100 text-pink-800',
}

/** Default badge color for categories not in the map. */
const DEFAULT_BADGE = 'bg-gray-100 text-gray-800'

function getCategoryColor(category: string): string {
  return CATEGORY_COLORS[category.toLowerCase()] || DEFAULT_BADGE
}

export default function Registry() {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const { data: apps, isLoading, error } = useQuery({
    queryKey: ['registry-apps'],
    queryFn: () => api.listApps(),
  })

  const refresh = useMutation({
    mutationFn: () => api.refreshRegistry(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['registry-apps'] })
    },
  })

  // Extract unique categories from loaded apps
  const categories = apps
    ? Array.from(new Set(apps.map((a: any) => a.category).filter(Boolean))).sort()
    : []

  // Filter apps by selected category (or show all)
  const filteredApps = selectedCategory
    ? apps?.filter((a: any) => a.category === selectedCategory)
    : apps

  const refreshButton = (
    <button
      onClick={() => refresh.mutate()}
      disabled={refresh.isPending}
      className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed inline-flex items-center gap-2"
    >
      {refresh.isPending ? (
        <>
          <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
          Refreshing...
        </>
      ) : (
        'Refresh from Git'
      )}
    </button>
  )

  const refreshStatus = refresh.isSuccess ? (
    <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4">
      <p className="text-sm text-green-700">
        Registry updated — {refresh.data?.registry?.app_count ?? 0} apps
        loaded from {refresh.data?.registry?.source === 'repo' ? 'git repo' : 'local templates'}
        {refresh.data?.repo?.action && ` (repo ${refresh.data.repo.action})`}
      </p>
    </div>
  ) : refresh.isError ? (
    <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
      <p className="text-sm text-red-700">
        Refresh failed: {refresh.error instanceof Error ? refresh.error.message : 'Unknown error'}
      </p>
    </div>
  ) : null

  if (isLoading) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">App Registry</h1>
          {refreshButton}
        </div>
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          <span className="ml-3 text-gray-500">Loading apps...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">App Registry</h1>
          {refreshButton}
        </div>
        {refreshStatus}
        <div className="bg-red-50 border border-red-200 rounded-lg p-4">
          <p className="text-sm text-red-700">
            {error instanceof Error ? error.message : 'Failed to load apps'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">App Registry</h1>
        {refreshButton}
      </div>

      {refreshStatus}

      {/* Category filter tabs */}
      <div className="flex flex-wrap gap-2 mb-6">
        <button
          onClick={() => setSelectedCategory(null)}
          className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
            selectedCategory === null
              ? 'bg-blue-600 text-white'
              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
          }`}
        >
          All
        </button>
        {categories.map((cat) => (
          <button
            key={cat as string}
            onClick={() =>
              setSelectedCategory(cat === selectedCategory ? null : (cat as string))
            }
            className={`px-3 py-1 rounded-full text-sm font-medium transition-colors ${
              selectedCategory === cat
                ? 'bg-blue-600 text-white'
                : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
            }`}
          >
            {cat as string}
          </button>
        ))}
      </div>

      {/* Empty state */}
      {(!filteredApps || filteredApps.length === 0) && (
        <div className="text-center py-12 text-gray-500">No apps found</div>
      )}

      {/* Card grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {filteredApps?.map((app: any) => (
          <div
            key={app.id}
            onClick={() => setExpandedId(expandedId === app.id ? null : app.id)}
            className="bg-white rounded-lg border p-4 hover:border-blue-500 transition-colors cursor-pointer"
          >
            {/* Header */}
            <div className="flex items-start justify-between">
              <h3 className="font-medium">{app.name || app.id}</h3>
              {app.category && (
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${getCategoryColor(app.category)}`}
                >
                  {app.category}
                </span>
              )}
            </div>

            {/* Description */}
            {app.description && (
              <p className="text-sm text-gray-500 mt-1">{app.description}</p>
            )}

            {/* Port */}
            {app.port && (
              <p className="text-xs text-gray-400 mt-2">
                Port: <span className="font-mono">{app.port}</span>
              </p>
            )}

            {/* Dependencies */}
            {app.dependencies && app.dependencies.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {app.dependencies.map((dep: string) => (
                  <span
                    key={dep}
                    className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded"
                  >
                    {dep}
                  </span>
                ))}
              </div>
            )}

            {/* Expanded metadata */}
            {expandedId === app.id && (
              <div className="mt-4 pt-4 border-t border-gray-100">
                <h4 className="text-xs font-semibold text-gray-500 uppercase mb-2">
                  Full Metadata
                </h4>
                <dl className="space-y-1">
                  {Object.entries(app).map(([key, value]) => {
                    // Skip fields already shown above
                    if (['id', 'name', 'description', 'category', 'port', 'dependencies'].includes(key)) {
                      return null
                    }
                    return (
                      <div key={key} className="flex text-xs">
                        <dt className="font-medium text-gray-500 w-32 shrink-0">{key}</dt>
                        <dd className="text-gray-700 font-mono break-all">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}
                        </dd>
                      </div>
                    )
                  })}
                </dl>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
