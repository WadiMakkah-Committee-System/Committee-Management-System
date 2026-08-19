import { getInitials } from '@/lib/utils'
import { cn } from '@/lib/utils'

const PALETTE = [
  'bg-brand-primary/10 text-brand-primary',
  'bg-brand-teal/10 text-brand-teal',
  'bg-brand-purple/10 text-brand-purple',
  'bg-brand-orange/10 text-brand-orange',
  'bg-brand-dark-blue/10 text-brand-dark-blue',
]

function hashToIndex(input: string): number {
  let hash = 0
  for (let i = 0; i < input.length; i++) hash = (hash + input.charCodeAt(i)) % PALETTE.length
  return hash
}

export function Avatar({
  firstName,
  lastName,
  size = 36,
  className,
}: {
  firstName: string
  lastName: string
  size?: number
  className?: string
}) {
  const palette = PALETTE[hashToIndex(firstName + lastName)]
  return (
    <div
      className={cn('flex shrink-0 items-center justify-center rounded-md font-semibold', palette, className)}
      style={{ width: size, height: size, fontSize: size * 0.38 }}
    >
      {getInitials(firstName, lastName)}
    </div>
  )
}
