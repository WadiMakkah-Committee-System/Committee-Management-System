/**
 * بيانات التواصل الرسمية لشركة وادي مكة للتقنية — المصدر الوحيد لها بالواجهة
 * (يستخدمها AppFooter حاليًا).
 *
 * المصدر: صفحة "اتصل بنا" بالموقع الرسمي https://wadimakkah.sa/اتصل-بنا/
 * (نُقلت كما هي بتاريخ 2026-10-29). عند تغيّرها بالموقع الرسمي تُحدَّث هنا فقط.
 */
export const COMPANY_INFO = {
  name: 'شركة وادي مكة للتقنية',
  nameEn: 'Wadi Makkah Company For Technology',
  /** الشركة مملوكة لجامعة أم القرى. */
  tagline: 'منصة إدارة اللجان — إحدى منصات شركة وادي مكة للتقنية، المملوكة لجامعة أم القرى',
  website: 'https://wadimakkah.sa/',
  contactPage: 'https://wadimakkah.sa/%d8%a7%d8%aa%d8%b5%d9%84-%d8%a8%d9%86%d8%a7/',
  address: 'العابدية – جامعة أم القرى، مكة المكرمة',
  /** العنوان الوطني المختصر (رقم المبنى / الرمز البريدي / الرقم الإضافي). */
  nationalAddress: 'مبنى 4229 · الرمز البريدي 24381 · الرقم الإضافي 7310',
  phone: { display: '+966 12 550 3322', href: 'tel:+966125503322' },
  fax: '+966 12 550 3344',
  email: 'info@wadimakkah.sa',
  social: {
    x: 'https://twitter.com/WadiMakkahSA',
    linkedin: 'https://www.linkedin.com/company/10931833/',
    instagram: 'https://www.instagram.com/WadiMakkahSA/',
    youtube: 'https://www.youtube.com/channel/UC74Wpv1INL53Esn0kknmdtw',
    facebook: 'https://www.facebook.com/WadiMakkahSA/',
  },
} as const
