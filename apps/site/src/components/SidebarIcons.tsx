import type { SVGProps } from "react";

export type SidebarIconProps = SVGProps<SVGSVGElement> & {
  size?: number;
};

function IconSvg({ size = 18, children, ...props }: SidebarIconProps & { children: React.ReactNode }): React.JSX.Element {
  return <svg aria-hidden="true" fill="none" height={size} viewBox="0 0 24 24" width={size} xmlns="http://www.w3.org/2000/svg" {...props}>{children}</svg>;
}

export function LayoutDashboardIcon(props: SidebarIconProps): React.JSX.Element {
  return <IconSvg {...props}><rect height="8" rx="1.5" stroke="currentColor" strokeWidth="1.7" width="8" x="3" y="3" /><rect height="5" rx="1.5" stroke="currentColor" strokeWidth="1.7" width="8" x="13" y="3" /><rect height="8" rx="1.5" stroke="currentColor" strokeWidth="1.7" width="8" x="3" y="13" /><rect height="11" rx="1.5" stroke="currentColor" strokeWidth="1.7" width="8" x="13" y="10" /></IconSvg>;
}

export function ActivityIcon(props: SidebarIconProps): React.JSX.Element {
  return <IconSvg {...props}><path d="M3 12h4l2.5-6.5L14 19l2.5-7H21" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" /></IconSvg>;
}

export function MessagesSquareIcon(props: SidebarIconProps): React.JSX.Element {
  return <IconSvg {...props}><path d="M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H11l-4.5 3V17H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.7" /><path d="M7 10h10M7 13h6" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" /></IconSvg>;
}

export function CreditCardIcon(props: SidebarIconProps): React.JSX.Element {
  return <IconSvg {...props}><rect height="14" rx="2" stroke="currentColor" strokeWidth="1.7" width="18" x="3" y="5" /><path d="M3 10h18" stroke="currentColor" strokeWidth="1.7" /><path d="M7 15h3" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" /></IconSvg>;
}

export function UserRoundIcon(props: SidebarIconProps): React.JSX.Element {
  return <IconSvg {...props}><circle cx="12" cy="8" r="4" stroke="currentColor" strokeWidth="1.7" /><path d="M4 21a8 8 0 0 1 16 0" stroke="currentColor" strokeLinecap="round" strokeWidth="1.7" /></IconSvg>;
}
