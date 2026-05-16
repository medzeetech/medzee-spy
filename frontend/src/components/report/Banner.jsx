import bannerImg from '../../assets/banner.png';

export default function Banner() {
  return (
    <a
      href="https://medzee.com.br"
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Você cuida dos seus pacientes. A MedZee cuida do resto. Testar agora."
      style={{
        display: 'block',
        marginBottom: 56,
        borderRadius: 16,
        overflow: 'hidden',
        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
        boxShadow: '0 10px 30px -10px rgba(255,107,53,0.35)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-2px)';
        e.currentTarget.style.boxShadow = '0 16px 40px -10px rgba(255,107,53,0.5)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        e.currentTarget.style.boxShadow = '0 10px 30px -10px rgba(255,107,53,0.35)';
      }}
    >
      <img
        src={bannerImg}
        alt=""
        style={{
          display: 'block',
          width: '100%',
          height: 'auto',
        }}
      />
    </a>
  );
}
