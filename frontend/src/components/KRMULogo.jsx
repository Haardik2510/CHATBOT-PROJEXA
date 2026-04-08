export default function KRMULogo({
  className = "",
  size = 56,
  alt = "K.R. Mangalam University logo",
}) {
  return (
    <img
      src="/krmu-mark.svg"
      alt={alt}
      width={size}
      height={size}
      className={className}
      loading="eager"
      decoding="async"
    />
  );
}
