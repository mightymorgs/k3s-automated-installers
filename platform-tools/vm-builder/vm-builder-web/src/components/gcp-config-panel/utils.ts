import { ZONE_SUFFIXES } from './constants'

export function zonesForRegion(region: string): string[] {
  return ZONE_SUFFIXES.map((suffix) => `${region}-${suffix}`)
}
