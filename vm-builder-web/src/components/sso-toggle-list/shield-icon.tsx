export default function ShieldIcon({ active }: { active: boolean }) {
  if (active) {
    return (
      <svg
        className="w-4 h-4 text-blue-600 flex-shrink-0"
        viewBox="0 0 24 24"
        fill="currentColor"
      >
        <path d="M12 2L3 7v5c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" />
      </svg>
    )
  }

  return (
    <svg
      className="w-4 h-4 text-gray-400 flex-shrink-0"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path d="M12 2L3 7v5c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5z" />
    </svg>
  )
}
