// Fields that use inventory/shared/config/ instead of inventory/shared/secrets/
const CONFIG_FIELDS: Record<string, Set<string>> = {
  github: new Set(['repo']),
  bws: new Set(['projectid']),
}

function bwsPath(category: string, key: string): string {
  const prefix = CONFIG_FIELDS[category]?.has(key) ? 'config' : 'secrets'
  return `inventory/shared/${prefix}/${category}/${key}`
}

export function secretExists(
  secrets: any[],
  category: string,
  key: string
): boolean | undefined {
  if (!secrets) {
    return undefined
  }

  const path = bwsPath(category, key)
  const found = secrets.find((secret: any) => secret.path === path)
  return found?.exists
}

export function categoryProgress(
  secrets: any[] | undefined,
  category: string
): { configured: number; total: number } {
  if (!secrets) {
    return { configured: 0, total: 0 }
  }

  const categorySecrets = secrets.filter((secret: any) =>
    secret.path.startsWith(`inventory/shared/secrets/${category}/`) ||
    secret.path.startsWith(`inventory/shared/config/${category}/`)
  )

  return {
    configured: categorySecrets.filter((secret: any) => secret.exists).length,
    total: categorySecrets.length,
  }
}

export function buildPayload(
  form: Record<string, Record<string, string>>
): Record<string, Record<string, string>> {
  const payload: Record<string, Record<string, string>> = {}

  for (const [category, fields] of Object.entries(form)) {
    const filtered: Record<string, string> = {}

    for (const [key, value] of Object.entries(fields)) {
      if (value.trim()) {
        filtered[key] = value.trim()
      }
    }

    if (Object.keys(filtered).length > 0) {
      payload[category] = filtered
    }
  }

  return payload
}
