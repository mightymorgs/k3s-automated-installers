import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import CategorySection from './category-section'
import { CATEGORY_LABELS, INITIAL_FORM } from './constants'
import ResultsPanel from './results-panel'
import { buildPayload } from './utils'

export default function InitSecretsPage() {
  const queryClient = useQueryClient()

  const [form, setForm] = useState<Record<string, Record<string, string>>>(INITIAL_FORM)
  const [overwrite, setOverwrite] = useState(false)

  const status = useQuery({
    queryKey: ['initStatus'],
    queryFn: api.initStatus,
  })

  const mutation = useMutation({
    mutationFn: (body: any) => api.initSecrets(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['initStatus'] })
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => api.refreshRegistry(),
  })

  const updateField = (category: string, key: string, value: string) => {
    setForm((prev) => ({
      ...prev,
      [category]: {
        ...prev[category],
        [key]: value,
      },
    }))
  }

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    const payload = buildPayload(form)
    mutation.mutate({ secrets: payload, overwrite })
  }

  const secrets = status.data?.secrets
  const totalSecrets = secrets?.length ?? 0
  const configuredSecrets = secrets?.filter((secret: any) => secret.exists).length ?? 0
  const progressPercent =
    totalSecrets > 0 ? Math.round((configuredSecrets / totalSecrets) * 100) : 0

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">Init Shared Secrets</h1>
      <p className="text-gray-600 mb-6">
        Configure shared infrastructure secrets stored in Bitwarden Secrets Manager.
      </p>

      {secrets && (
        <div className="mb-6">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-700">Setup Progress</span>
            <span className="text-sm text-gray-500">
              {configuredSecrets} of {totalSecrets} secrets configured
            </span>
          </div>
          <div className="w-full bg-gray-200 rounded-full h-2.5">
            <div
              className={`h-2.5 rounded-full transition-all duration-500 ${
                progressPercent === 100
                  ? 'bg-green-500'
                  : progressPercent > 50
                    ? 'bg-blue-500'
                    : 'bg-yellow-500'
              }`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>
      )}

      {status.isLoading && <p className="text-gray-500 mb-4">Loading secret status...</p>}
      {status.isError && (
        <p className="text-red-600 mb-4">
          Failed to load secret status: {(status.error as Error).message}
        </p>
      )}

      <form onSubmit={handleSubmit}>
        {Object.entries(CATEGORY_LABELS).map(([category, label]) => (
          <CategorySection
            key={category}
            category={category}
            label={label}
            formValues={form[category]}
            secrets={secrets}
            onUpdateField={updateField}
          />
        ))}

        <div className="bg-white rounded-lg border p-6 mb-4">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(event) => setOverwrite(event.target.checked)}
              className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm font-medium text-gray-700">Overwrite existing secrets</span>
          </label>
          <p className="text-xs text-gray-500 mt-1 ml-6">
            When unchecked, existing secrets in BWS will be skipped.
          </p>
        </div>

        <button
          type="submit"
          disabled={mutation.isPending}
          className="bg-blue-600 text-white px-6 py-2 rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {mutation.isPending ? 'Saving...' : 'Save Secrets'}
        </button>
      </form>

      {mutation.isSuccess && mutation.data?.results && <ResultsPanel results={mutation.data.results} />}

      {mutation.isError && (
        <div className="mt-6 bg-red-50 rounded-lg border border-red-200 p-4">
          <p className="text-red-700 text-sm">
            Failed to save secrets: {(mutation.error as Error).message}
          </p>
        </div>
      )}

      {/* Sync Repository button — shown after successful save */}
      {mutation.isSuccess && (
        <div className="mt-6 bg-white rounded-lg border p-6">
          <h2 className="text-lg font-semibold mb-2">Sync Repository</h2>
          <p className="text-sm text-gray-600 mb-4">
            Clone or update the enterprise templates repository using the GitHub PAT you just saved.
          </p>
          <button
            type="button"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="bg-green-600 text-white px-6 py-2 rounded-md hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {syncMutation.isPending ? 'Syncing...' : 'Sync Repository'}
          </button>
          {syncMutation.isSuccess && (
            <p className="mt-2 text-sm text-green-700">
              Repository synced successfully.
            </p>
          )}
          {syncMutation.isError && (
            <p className="mt-2 text-sm text-red-700">
              Sync failed: {(syncMutation.error as Error).message}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
