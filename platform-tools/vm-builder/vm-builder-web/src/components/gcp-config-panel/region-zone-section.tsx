import { REGION_OPTIONS } from './constants'

interface RegionZoneSectionProps {
  region: string
  zone: string
  availableZones: string[]
  onChangeRegion: (region: string) => void
  onChangeZone: (zone: string) => void
}

export default function RegionZoneSection({
  region,
  zone,
  availableZones,
  onChangeRegion,
  onChangeZone,
}: RegionZoneSectionProps) {
  return (
    <div>
      <h3 className="text-sm font-semibold text-gray-700 uppercase tracking-wide mb-3">
        Region &amp; Zone
      </h3>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Region</label>
          <select
            value={region}
            onChange={(e) => onChangeRegion(e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            {REGION_OPTIONS.map((regionOption) => (
              <option key={regionOption} value={regionOption}>
                {regionOption}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Zone</label>
          <select
            value={zone}
            onChange={(e) => onChangeZone(e.target.value)}
            className="w-full border rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            {availableZones.map((zoneOption) => (
              <option key={zoneOption} value={zoneOption}>
                {zoneOption}
              </option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )
}
