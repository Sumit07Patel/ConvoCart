// Part 1: the Kesar Lane brand site. Kesar Lane is a fictional label; every product, price and order behind it
// is simulated. Photos are from Unsplash (free under the Unsplash License), credited in the footer.
// Category tiles carry no prices: prices come live from the store in the chat.

export const PHOTOS = {
  rain: "photo-1527192250228-1ece59813102",     // Dadee Aissa
  saree: "photo-1742287724816-4a8a1cc7ad5c",    // Himanshu Dewangan
  kurta: "photo-1744208525808-66c60e0ea68c",    // Equator Stores
  sneakers: "photo-1736555142217-916540c7f1b7", // Dmytro Shyrokov
  winter: "photo-1668934804959-2cc138045bfb",   // Jay Wennington
  basics: "photo-1629426958003-35a5583b2977",   // Chase Charaba
};

export function photo(id: string, w: number, h?: number): string {
  return `https://images.unsplash.com/${id}?auto=format&fit=crop&q=75&w=${w}${h ? `&h=${h}` : ""}`;
}

const CATEGORIES = [
  { name: "Monsoon", kind: "Rain jackets & windcheaters", img: PHOTOS.rain, ask: "monsoon ke liye halki waterproof jacket dikhao, 3000 ke andar" },
  { name: "Sarees", kind: "Silk, handloom, party", img: PHOTOS.saree, ask: "show me a saree for a wedding" },
  { name: "Kurtas", kind: "Cotton & linen, everyday", img: PHOTOS.kurta, ask: "office ke liye cotton kurta dikhao" },
  { name: "Sneakers", kind: "Footwear for wet pavements", img: PHOTOS.sneakers, ask: "बारिश के लिए जूते दिखाओ" },
  { name: "Winter", kind: "Jackets & hoodies", img: PHOTOS.winter, ask: "Delhi winter ke liye warm jacket" },
  { name: "Basics", kind: "Tees, shirts & jeans", img: PHOTOS.basics, ask: "black t-shirt in size L" },
];

export default function Brand({ onAsk }: { onAsk: (text: string) => void }) {
  return (
    <>
      <section className="hero" aria-label="The Monsoon Edit">
        <div className="hero-panel hero-main">
          <img src={photo(PHOTOS.rain, 1100, 1400)} alt="A person in a yellow raincoat walking down a wet street" />
          <div className="hero-copy">
            <p className="kicker">The Monsoon Edit · 2026</p>
            <h1 className="display">Made for monsoons.<br /><em>And Mondays.</em></h1>
            <div className="cta-row">
              <a href="#collections" className="btn btn-light">Shop the edit</a>
              <a href="#assistant" className="btn btn-outline-light">Ask our stylist</a>
            </div>
          </div>
        </div>
        <a className="hero-panel hero-side" href="#collections">
          <img src={photo(PHOTOS.saree, 900, 1200)} alt="A woman in a pink and black silk saree" />
          <span className="hero-caption">Silk sarees for the wedding season <span aria-hidden="true">→</span></span>
        </a>
      </section>

      <section id="collections" className="wrap section">
        <div className="section-head">
          <h2 className="display-sm">Shop by category</h2>
          <p className="muted">Tap a category and our stylist finds it for you, in English, हिंदी or Hinglish.</p>
        </div>
        <div className="categories">
          {CATEGORIES.map((c) => (
            <article key={c.name} className="cat">
              <button type="button" className="cat-img" onClick={() => onAsk(c.ask)} aria-label={`Ask the stylist about ${c.name}`}>
                <img src={photo(c.img, 600, 800)} alt="" loading="lazy" />
                <span className="cat-name">{c.name}</span>
              </button>
              <p className="cat-kind">{c.kind}</p>
              <button type="button" className="ask-link" onClick={() => onAsk(c.ask)}>
                Ask: <span lang={/[ऀ-ॿ]/.test(c.ask) ? "hi" : undefined}>“{c.ask}”</span>
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="stylist">
        <div className="stylist-img">
          <img src={photo(PHOTOS.kurta, 900, 1100)} alt="A man in a light blue kurta" loading="lazy" />
        </div>
        <div className="stylist-copy">
          <p className="kicker dark">Meet your stylist</p>
          <h2 className="display-sm">It speaks Hinglish.<br />It never makes up a price.</h2>
          <p className="lede">Ask for “pehla wala, size M” and it lands in your cart. Bargain a little, and it tells you
            exactly what it can do. Leave, and we'll send one friendly email with your cart, never more.</p>
          <a href="#assistant" className="teaser" aria-label="Open the shopping assistant">
            <p className="t-out">monsoon ke liye halki jacket dikhao 3000 ke andar</p>
            <p className="t-in">Monsoon ke liye halki jackets, ₹3000 ke andar:<br />
              1. <b>Kesar Lane Drizzle Windcheater</b> · ₹2,599<br />
              <span className="t-dim">Sizes XS to XXL · black, grey, navy, olive</span><br />
              Kaunsa size chahiye?</p>
            <span className="teaser-foot">A real reply from the agent. Try your own →</span>
          </a>
        </div>
      </section>

      <section id="promise" className="promise">
        <div className="wrap promise-grid">
          <div><h3>15-day returns</h3><p>Changed your mind? Return or exchange within 15 days of delivery.</p></div>
          <div><h3>Honest prices</h3><p>Every price comes straight from the store. Discounts have a clear cap, for everyone.</p></div>
          <div><h3>A person when you need one</h3><p>Ask for a human and our team picks up the same chat. No repeating yourself.</p></div>
        </div>
      </section>
    </>
  );
}
