import SecretInput from '../../components/SecretInput'
import { CATEGORY_DESCRIPTIONS, FIELD_LABELS } from './constants'
import { categoryProgress, secretExists } from './utils'

interface CategorySectionProps {
  category: string
  label: string
  formValues: Record<string, string>
  secrets: any[] | undefined
  onUpdateField: (category: string, key: string, value: string) => void
}

export default function CategorySection({
  category,
  label,
  formValues,
  secrets,
  onUpdateField,
}: CategorySectionProps) {
  const progress = categoryProgress(secrets, category)

  return (
    <div className="bg-white rounded-lg border p-6 mb-4">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold">{label}</h2>
        {secrets &&
          (progress.configured === progress.total && progress.total > 0 ? (
            <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded-full font-medium">
              Complete
            </span>
          ) : (
            <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full font-medium">
              {progress.configured}/{progress.total}
            </span>
          ))}
      </div>
      {CATEGORY_DESCRIPTIONS[category] && (
        <p className="text-sm text-gray-500 mb-4">{CATEGORY_DESCRIPTIONS[category]}</p>
      )}
      {category === 'console' && (
        <div className="bg-blue-50 border border-blue-200 rounded-md p-3 mb-4">
          <p className="text-sm text-blue-800">
            <span className="font-semibold">Admin Credentials</span> — The username and
            password you set here become the admin account for every VM provisioned by
            vm-builder. This account is used for SSH login, sudo access, and initial
            console access on each virtual machine.
          </p>
        </div>
      )}
      {Object.entries(FIELD_LABELS[category]).map(([key, fieldLabel]) => (
        <SecretInput
          key={`${category}-${key}`}
          label={fieldLabel}
          name={`${category}.${key}`}
          value={formValues[key]}
          onChange={(value) => onUpdateField(category, key, value)}
          exists={secretExists(secrets || [], category, key)}
        />
      ))}
    </div>
  )
}
