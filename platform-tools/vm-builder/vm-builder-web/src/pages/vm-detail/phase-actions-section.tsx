import { UseMutationResult } from '@tanstack/react-query'

interface PhaseAction {
  label: string
  description: string
  mutation: UseMutationResult<any, Error, void>
  color: string
  hoverColor: string
}

interface PhaseActionsSectionProps {
  deployMutation: UseMutationResult<any, Error, void>
  installAppsMutation: UseMutationResult<any, Error, void>
  configureAppsMutation: UseMutationResult<any, Error, void>
  ingressSsoMutation: UseMutationResult<any, Error, void>
}

function RunLink({ data }: { data: any }) {
  if (!data?.run_url) return null
  return (
    <a
      href={data.run_url}
      target="_blank"
      rel="noopener noreferrer"
      className="text-xs text-blue-600 hover:text-blue-800 underline ml-2"
    >
      View run
    </a>
  )
}

export default function PhaseActionsSection({
  deployMutation,
  installAppsMutation,
  configureAppsMutation,
  ingressSsoMutation,
}: PhaseActionsSectionProps) {
  const phases: PhaseAction[] = [
    {
      label: 'Deploy VM',
      description: 'Provision VM infrastructure (Phase 2)',
      mutation: deployMutation,
      color: 'bg-blue-600',
      hoverColor: 'hover:bg-blue-700',
    },
    {
      label: 'Install Apps',
      description: 'Install selected apps on the VM (Phase 3)',
      mutation: installAppsMutation,
      color: 'bg-green-600',
      hoverColor: 'hover:bg-green-700',
    },
    {
      label: 'Configure Apps',
      description: 'Run config playbooks for installed apps (Phase 4)',
      mutation: configureAppsMutation,
      color: 'bg-yellow-600',
      hoverColor: 'hover:bg-yellow-700',
    },
    {
      label: 'Configure Ingress + SSO',
      description: 'Deploy Traefik ingress and Authentik SSO (Phase 5)',
      mutation: ingressSsoMutation,
      color: 'bg-purple-600',
      hoverColor: 'hover:bg-purple-700',
    },
  ]

  const anyPending = phases.some((p) => p.mutation.isPending)

  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-50 border-b border-gray-200 px-4 py-2">
        <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
          Deployment Phases
        </h2>
      </div>
      <div className="p-4 grid grid-cols-2 gap-3">
        {phases.map((phase) => {
          const isPending = phase.mutation.isPending
          const isSuccess = phase.mutation.isSuccess
          const isError = phase.mutation.isError

          return (
            <div
              key={phase.label}
              className="border border-gray-200 rounded-md p-3 flex flex-col justify-between"
            >
              <div>
                <p className="text-sm font-medium text-gray-900">{phase.label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{phase.description}</p>
              </div>
              <div className="mt-3 flex items-center">
                <button
                  onClick={() => phase.mutation.mutate()}
                  disabled={isPending || anyPending}
                  className={`px-3 py-1.5 text-sm text-white rounded disabled:opacity-50 ${phase.color} ${phase.hoverColor}`}
                >
                  {isPending ? 'Running...' : phase.label}
                </button>
                {isSuccess && (
                  <>
                    <span className="text-xs text-green-600 ml-2">Triggered</span>
                    <RunLink data={phase.mutation.data} />
                  </>
                )}
                {isError && (
                  <span className="text-xs text-red-600 ml-2">
                    {(phase.mutation.error as Error).message}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
