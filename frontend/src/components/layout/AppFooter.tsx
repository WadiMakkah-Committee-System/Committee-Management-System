import type { ReactNode } from 'react'
import { Globe, Mail, MapPin, Phone, Printer } from 'lucide-react'
import wadiMakkahMark from '@/assets/wadi-makkah-mark.png'
import { COMPANY_INFO } from '@/lib/companyInfo'

/**
 * أيقونات حسابات التواصل — SVG مضمّنة لأن lucide-react (v1) لم تعد تشمل
 * شعارات المنصات. currentColor فتأخذ لون النص (يعمل بالوضعين الفاتح والداكن).
 */
const SOCIAL_ICONS: Record<keyof typeof COMPANY_INFO.social, { label: string; icon: ReactNode }> = {
  x: {
    label: 'X (تويتر)',
    icon: (
      <path d="M18.9 1.15h3.68l-8.04 9.19L24 22.85h-7.4l-5.8-7.59-6.64 7.59H.47l8.6-9.83L0 1.15h7.6l5.24 6.93 6.06-6.93Zm-1.29 19.5h2.04L6.48 3.24H4.3l13.31 17.41Z" />
    ),
  },
  linkedin: {
    label: 'LinkedIn',
    icon: (
      <path d="M4.98 3.5a2.48 2.48 0 1 1-4.96 0 2.48 2.48 0 0 1 4.96 0ZM.5 8h4v16h-4V8Zm7.5 0h3.8v2.2h.06c.53-1 1.83-2.2 3.78-2.2 4.04 0 4.79 2.66 4.79 6.12V24h-4v-7.1c0-1.7-.03-3.87-2.36-3.87-2.36 0-2.72 1.84-2.72 3.75V24H8V8Z" />
    ),
  },
  instagram: {
    label: 'Instagram',
    icon: (
      <>
        <rect x="2" y="2" width="20" height="20" rx="5.5" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="12" cy="12" r="4.5" fill="none" stroke="currentColor" strokeWidth="2" />
        <circle cx="17.6" cy="6.4" r="1.3" />
      </>
    ),
  },
  youtube: {
    label: 'YouTube',
    icon: (
      <path d="M23.5 6.2a3 3 0 0 0-2.1-2.13C19.5 3.55 12 3.55 12 3.55s-7.5 0-9.4.52A3 3 0 0 0 .5 6.2C0 8.1 0 12 0 12s0 3.9.5 5.8a3 3 0 0 0 2.1 2.13c1.9.52 9.4.52 9.4.52s7.5 0 9.4-.52a3 3 0 0 0 2.1-2.13c.5-1.9.5-5.8.5-5.8s0-3.9-.5-5.8ZM9.6 15.57V8.43L15.82 12 9.6 15.57Z" />
    ),
  },
  facebook: {
    label: 'Facebook',
    icon: (
      <path d="M24 12.07C24 5.4 18.63 0 12 0S0 5.4 0 12.07C0 18.1 4.39 23.1 10.13 24v-8.44H7.08v-3.49h3.05V9.41c0-3.02 1.79-4.69 4.53-4.69 1.31 0 2.69.24 2.69.24v2.97h-1.52c-1.49 0-1.96.93-1.96 1.88v2.26h3.33l-.53 3.49h-2.8V24C19.61 23.1 24 18.1 24 12.07Z" />
    ),
  },
}

/** سطر تواصل واحد (أيقونة + محتوى) بعمود "تواصل معنا". */
function ContactRow({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <li className="flex items-start gap-2.5 text-sm text-text-secondary">
      <span className="mt-0.5 shrink-0 text-brand-primary">{icon}</span>
      <span className="min-w-0">{children}</span>
    </li>
  )
}

/** عنوان عمود بالفوتر. */
function ColumnTitle({ children }: { children: ReactNode }) {
  return <h2 className="mb-3 text-sm font-bold text-text-primary">{children}</h2>
}

/**
 * الهدف: تذييل موحّد لكل صفحات النظام بعد تسجيل الدخول (طلب صاحبة المشروع
 * 2026-10-29) — لا يظهر بصفحة الدخول ولا بالشاشة الافتتاحية لأنهما خارج AppShell.
 *
 * المحتوى: هوية الشركة، بيانات التواصل الرسمية، حسابات التواصل الاجتماعي،
 * وسطر الحقوق — كلها من COMPANY_INFO (src/lib/companyInfo.ts).
 * الألوان من tokens الهوية فقط، ويعمل بالوضعين الفاتح والداكن.
 *
 * بلا تأثيرات جانبية ولا استدعاءات API. الروابط الخارجية تفتح بتبويب جديد.
 */
export function AppFooter() {
  const year = new Date().getFullYear()

  return (
    <footer className="relative mt-8 border-t border-border-default bg-bg-surface">
      <div aria-hidden className="brand-stripe absolute inset-x-0 top-0 h-[2px] opacity-70" />

      <div className="grid grid-cols-1 gap-8 px-4 py-8 sm:px-6 md:grid-cols-2 lg:grid-cols-[1.4fr_1.2fr_1fr] lg:px-8">
        {/* الهوية */}
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-3">
            <img src={wadiMakkahMark} alt="شعار وادي مكة" className="h-9 w-auto shrink-0" />
            <div className="leading-tight">
              <p className="text-sm font-bold text-text-primary">{COMPANY_INFO.name}</p>
              <p className="text-xs text-text-muted" dir="ltr">
                {COMPANY_INFO.nameEn}
              </p>
            </div>
          </div>
          <p className="max-w-sm text-sm leading-6 text-text-muted">{COMPANY_INFO.tagline}</p>
        </div>

        {/* تواصل معنا */}
        <div>
          <ColumnTitle>تواصل معنا</ColumnTitle>
          <ul className="flex flex-col gap-2.5">
            <ContactRow icon={<MapPin size={16} />}>
              <span className="block">{COMPANY_INFO.address}</span>
              <span className="block text-xs text-text-muted">{COMPANY_INFO.nationalAddress}</span>
            </ContactRow>
            <ContactRow icon={<Phone size={16} />}>
              <a href={COMPANY_INFO.phone.href} dir="ltr" className="transition-colors hover:text-brand-primary">
                {COMPANY_INFO.phone.display}
              </a>
            </ContactRow>
            <ContactRow icon={<Printer size={16} />}>
              <span dir="ltr">{COMPANY_INFO.fax}</span>
              <span className="text-xs text-text-muted"> (فاكس)</span>
            </ContactRow>
            <ContactRow icon={<Mail size={16} />}>
              <a href={`mailto:${COMPANY_INFO.email}`} className="transition-colors hover:text-brand-primary">
                {COMPANY_INFO.email}
              </a>
            </ContactRow>
          </ul>
        </div>

        {/* روابط وتابعنا */}
        <div>
          <ColumnTitle>روابط</ColumnTitle>
          <ul className="mb-5 flex flex-col gap-2.5">
            <ContactRow icon={<Globe size={16} />}>
              <a
                href={COMPANY_INFO.website}
                target="_blank"
                rel="noopener noreferrer"
                className="transition-colors hover:text-brand-primary"
              >
                الموقع الرسمي للشركة
              </a>
            </ContactRow>
          </ul>

          <ColumnTitle>تابعنا على</ColumnTitle>
          <ul className="flex flex-wrap gap-2">
            {(Object.keys(SOCIAL_ICONS) as (keyof typeof SOCIAL_ICONS)[]).map((key) => (
              <li key={key}>
                <a
                  href={COMPANY_INFO.social[key]}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={SOCIAL_ICONS[key].label}
                  title={SOCIAL_ICONS[key].label}
                  className="flex h-9 w-9 items-center justify-center rounded-sm border border-border-default text-text-secondary transition-colors hover:border-brand-primary/40 hover:bg-brand-primary/10 hover:text-brand-primary"
                >
                  <svg viewBox="0 0 24 24" width={16} height={16} fill="currentColor" aria-hidden>
                    {SOCIAL_ICONS[key].icon}
                  </svg>
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="flex flex-col items-center justify-between gap-2 border-t border-border-default px-4 py-4 text-xs text-text-muted sm:flex-row sm:px-6 lg:px-8">
        <p>
          © {year} {COMPANY_INFO.name} — جميع الحقوق محفوظة
        </p>
        <p>منصة إدارة اللجان</p>
      </div>
    </footer>
  )
}
