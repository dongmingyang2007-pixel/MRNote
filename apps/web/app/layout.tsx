export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // next-intl requires the [locale] layout to own <html>/<body>.
  // Root layout is a pass-through.
  return children as React.ReactElement;
}
