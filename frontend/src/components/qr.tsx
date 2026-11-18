import qrcode from "qrcode-generator";
export function QR({ url }: { url: string; }) {
  const qr = qrcode(0, "M");
  qr.addData(url);
  qr.make();
  return (
    <div
      dangerouslySetInnerHTML={{
        __html: qr.createSvgTag({ cellSize: 3, margin: 2, scalable: true }),
      }}
    />
  );
}
