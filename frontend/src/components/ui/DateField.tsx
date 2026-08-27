import { useEffect, useState } from 'react'

interface DateFieldProps {
  label?: string
  required?: boolean
  error?: string
  hint?: string
  /** القيمة الحالية بصيغة ISO (yyyy-mm-dd) — نفس صيغة حقول <input type="date"> القياسية، أو '' لعدم التحديد. */
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

/**
 * الهدف:
 * حقل تاريخ مبني من ثلاثة صناديق أرقام (يوم/شهر/سنة) بدل <input
 * type="date"> الأصلي — لأن تنسيق عرض التاريخ بالمتصفح لعنصر "date"
 * القياسي يتبع لغة/إعدادات نظام تشغيل المتصفح نفسه وليس اتجاه الصفحة
 * (dir="rtl") ولا حتى خاصية lang بالعنصر بشكل موثوق عبر كل المتصفحات —
 * فكان يظهر أحيانًا بترتيب معكوس (مثال: شهر/يوم/سنة) رغم أن الواجهة كلها
 * RTL. هذا المكوّن يضمن ترتيب "يوم / شهر / سنة" دائمًا، بصريًا ومنطقيًا.
 *
 * المسؤولية:
 * عرض/تعديل ثلاثة أجزاء (يوم، شهر، سنة) بترتيب ثابت، والتحقق من صحة كل
 * جزء (يوم 1-31، شهر 1-12، سنة 4 أرقام)، وتحويلها لصيغة ISO (yyyy-mm-dd)
 * عبر onChange فقط عند اكتمال الأجزاء الثلاثة بشكل صالح — نفس الصيغة
 * التي تتوقعها بقية النماذج (متوافقة تمامًا مع <input type="date"> سابقًا،
 * فلا حاجة لتعديل أي منطق إرسال/تحقق (Zod) بالنماذج المستخدمة فيها).
 *
 * التأثيرات الجانبية: onChange تُستدعى بقيمة '' إذا كان أي جزء ناقصًا أو
 * غير صالح (نفس سلوك input فارغ)، ما يبقي الحقل متوافقًا مع قواعد
 * required/min(1) الموجودة بالنماذج المستدعية دون تعديل.
 */
export function DateField({ label, required, error, hint, value, onChange, disabled }: DateFieldProps) {
  const [day, setDay] = useState('')
  const [month, setMonth] = useState('')
  const [year, setYear] = useState('')

  // يزامن الأجزاء الثلاثة مع value الخارجية (مثال: عند فتح نموذج تعديل بتاريخ موجود مسبقًا).
  useEffect(() => {
    const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
    if (match) {
      setYear(match[1])
      setMonth(String(Number(match[2])))
      setDay(String(Number(match[3])))
    } else if (!value) {
      setDay('')
      setMonth('')
      setYear('')
    }
  }, [value])

  function emit(nextDay: string, nextMonth: string, nextYear: string) {
    const d = Number(nextDay)
    const m = Number(nextMonth)
    const y = Number(nextYear)
    const valid =
      nextDay !== '' &&
      nextMonth !== '' &&
      nextYear.length === 4 &&
      d >= 1 &&
      d <= 31 &&
      m >= 1 &&
      m <= 12 &&
      y >= 1000

    if (!valid) {
      onChange('')
      return
    }
    const iso = `${String(y).padStart(4, '0')}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    onChange(iso)
  }

  const boxClass =
    'h-10 w-full min-w-0 rounded-sm border bg-bg-surface px-2 text-center text-sm text-text-primary ' +
    'transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-brand-accent/40 ' +
    (error ? 'border-danger focus:border-danger' : 'border-border-default focus:border-brand-primary') +
    (disabled ? ' cursor-not-allowed opacity-60' : '')

  return (
    <div className="flex flex-col gap-1.5">
      {label && (
        <label className="text-sm font-medium text-text-primary">
          {label}
          {required && <span className="text-danger"> *</span>}
        </label>
      )}
      <div className="flex items-center gap-1.5">
        <input
          type="number"
          inputMode="numeric"
          placeholder="يوم"
          aria-label={label ? `${label} — يوم` : 'يوم'}
          min={1}
          max={31}
          disabled={disabled}
          value={day}
          onChange={(e) => {
            const v = e.target.value.slice(0, 2)
            setDay(v)
            emit(v, month, year)
          }}
          className={boxClass}
        />
        <span className="text-text-muted">/</span>
        <input
          type="number"
          inputMode="numeric"
          placeholder="شهر"
          aria-label={label ? `${label} — شهر` : 'شهر'}
          min={1}
          max={12}
          disabled={disabled}
          value={month}
          onChange={(e) => {
            const v = e.target.value.slice(0, 2)
            setMonth(v)
            emit(day, v, year)
          }}
          className={boxClass}
        />
        <span className="text-text-muted">/</span>
        <input
          type="number"
          inputMode="numeric"
          placeholder="سنة"
          aria-label={label ? `${label} — سنة` : 'سنة'}
          min={1000}
          max={9999}
          disabled={disabled}
          value={year}
          onChange={(e) => {
            const v = e.target.value.slice(0, 4)
            setYear(v)
            emit(day, month, v)
          }}
          className={boxClass + ' flex-[1.3]'}
        />
      </div>
      {error ? (
        <p className="text-xs font-medium text-danger">{error}</p>
      ) : hint ? (
        <p className="text-xs text-text-muted">{hint}</p>
      ) : null}
    </div>
  )
}
