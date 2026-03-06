import { RegistryApp } from './types'

export function groupAppsByCategory(apps: RegistryApp[]): Record<string, RegistryApp[]> {
  const grouped: Record<string, RegistryApp[]> = {}
  for (const app of apps) {
    const category = app.category || 'other'
    if (!grouped[category]) {
      grouped[category] = []
    }
    grouped[category].push(app)
  }
  return grouped
}
