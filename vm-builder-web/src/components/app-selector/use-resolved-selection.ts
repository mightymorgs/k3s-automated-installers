import { useEffect, useState } from 'react'
import { api } from '../../api/client'

interface UseResolvedSelectionArgs {
  selected: string[]
  onChange: (apps: string[]) => void
}

export function useResolvedSelection({
  selected,
  onChange,
}: UseResolvedSelectionArgs): {
  autoDeps: Record<string, string>
  userSelected: string[]
  setUserSelected: (next: string[]) => void
} {
  const [autoDeps, setAutoDeps] = useState<Record<string, string>>({})
  const [userSelected, setUserSelected] = useState<string[]>(selected)

  useEffect(() => {
    if (userSelected.length === 0) {
      setAutoDeps({})
      onChange([])
      return
    }

    api
      .resolveDeps(userSelected)
      .then((result: any) => {
        const allApps: string[] = result.resolved || result.apps || []
        const newAutoDeps: Record<string, string> = {}

        for (const app of allApps) {
          if (!userSelected.includes(app)) {
            newAutoDeps[app] =
              userSelected.find((selectedApp) => allApps.includes(selectedApp)) ||
              'selected apps'
          }
        }

        setAutoDeps(newAutoDeps)
        onChange(allApps)
      })
      .catch(() => {
        setAutoDeps({})
        onChange(userSelected)
      })
  }, [userSelected, onChange])

  return {
    autoDeps,
    userSelected,
    setUserSelected,
  }
}
