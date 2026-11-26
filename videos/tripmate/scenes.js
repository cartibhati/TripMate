export default {
  intro(s) {
    const { top, left, w, h } = s.safe;
    const u = Math.min(w, h) / 100;

    s.title('TripMate AI', {
      y: top + h * 0.22,
      size: u * 13,
      at: -1
    });

    s.box('Multi-Agent Travel Planner', {
      id: 'sub',
      y: top + h * 0.44,
      w: w * 0.58,
      h: h * 0.13,
      color: 'accent',
      icon: 'sparkles',
      size: u * 4.6,
      at: 0.1
    });

    s.box('LangGraph', {
      id: 'lg',
      x: left + w * 0.22,
      y: top + h * 0.72,
      w: w * 0.26,
      h: h * 0.16,
      color: 'blue',
      icon: 'git-branch',
      size: u * 4.0,
      at: 'langgraph'
    });

    s.box('FastAPI', {
      id: 'fa',
      x: left + w * 0.50,
      y: top + h * 0.72,
      w: w * 0.24,
      h: h * 0.16,
      color: 'teal',
      icon: 'server',
      size: u * 4.0,
      at: 'fastapi'
    });

    s.box('Groq LPU', {
      id: 'gq',
      x: left + w * 0.78,
      y: top + h * 0.72,
      w: w * 0.26,
      h: h * 0.16,
      color: 'orange',
      icon: 'zap',
      size: u * 4.0,
      at: 'groq'
    });
  },

  architecture(s) {
    const { top, left, w, h } = s.safe;
    const u = Math.min(w, h) / 100;

    s.title('Guardrail, Supervisor & Parallel Agents', {
      y: top + h * 0.10,
      size: u * 7.2,
      at: 0
    });

    s.box('Input Guardrail\nBlocks Off-Topic', {
      id: 'guard',
      x: left + w * 0.26,
      y: top + h * 0.30,
      w: w * 0.36,
      h: h * 0.16,
      color: 'red',
      icon: 'shield-check',
      size: u * 3.6,
      at: 'guardrail'
    });

    s.box('Supervisor Router\nConstraints + Routing', {
      id: 'sup',
      x: left + w * 0.74,
      y: top + h * 0.30,
      w: w * 0.38,
      h: h * 0.16,
      color: 'purple',
      icon: 'cpu',
      size: u * 3.6,
      at: 'supervisor'
    });

    s.arrow('guard', 'sup', { at: 'supervisor' });

    const colW = w * 0.27;
    const yMid = top + h * 0.58;

    s.box('Flight Agent\nHubs & Routes', {
      id: 'flight',
      x: left + w * 0.18,
      y: yMid,
      w: colW,
      h: h * 0.18,
      color: 'blue',
      icon: 'plane',
      size: u * 3.6,
      at: 'flight'
    });

    s.box('Hotel Agent\nTavily Search', {
      id: 'hotel',
      x: left + w * 0.50,
      y: yMid,
      w: colW,
      h: h * 0.18,
      color: 'teal',
      icon: 'building',
      size: u * 3.6,
      at: 'hotel'
    });

    s.box('Weather Agent\nOpen-Meteo Live', {
      id: 'weather',
      x: left + w * 0.82,
      y: yMid,
      w: colW,
      h: h * 0.18,
      color: 'orange',
      icon: 'cloud-sun',
      size: u * 3.6,
      at: 'open-meteo'
    });

    s.box('Budget Analyst → 7-Section Draft', {
      id: 'budget',
      x: s.cx,
      y: top + h * 0.86,
      w: w * 0.72,
      h: h * 0.14,
      color: 'yellow',
      icon: 'wallet',
      size: u * 3.8,
      at: 'budget'
    });

    s.arrow('flight', 'budget', { at: 'budget' });
    s.arrow('hotel', 'budget', { at: 'budget' });
    s.arrow('weather', 'budget', { at: 'budget' });
  },

  hitl(s) {
    const { top, left, w, h } = s.safe;
    const u = Math.min(w, h) / 100;

    s.title('Human-in-the-Loop & Persistence', {
      y: top + h * 0.12,
      size: u * 7.6,
      at: 0
    });

    s.box('LangGraph Interrupt\nPaused for Your Review', {
      id: 'pause',
      x: s.cx,
      y: top + h * 0.34,
      w: w * 0.56,
      h: h * 0.16,
      color: 'orange',
      icon: 'pause-circle',
      size: u * 4.0,
      at: 'pauses'
    });

    s.box('Approve & Finalize\nInstant Polish', {
      id: 'approve',
      x: left + w * 0.28,
      y: top + h * 0.62,
      w: w * 0.36,
      h: h * 0.16,
      color: 'green',
      icon: 'check',
      size: u * 3.8,
      at: 'approve'
    });

    s.box('Request Revision\nApply Feedback', {
      id: 'revise',
      x: left + w * 0.72,
      y: top + h * 0.62,
      w: w * 0.36,
      h: h * 0.16,
      color: 'purple',
      icon: 'edit-3',
      size: u * 3.8,
      at: 'revisions'
    });

    s.box('PostgreSQL Checkpoint Memory', {
      id: 'pg',
      x: s.cx,
      y: top + h * 0.86,
      w: w * 0.62,
      h: h * 0.12,
      color: 'blue',
      icon: 'database',
      size: u * 3.8,
      at: 'postgresql'
    });

    s.arrow('pause', 'approve', { at: 'approve' });
    s.arrow('pause', 'revise', { at: 'revisions' });
  },

  outro(s) {
    const { top, w, h } = s.safe;
    const u = Math.min(w, h) / 100;

    s.title('Plan Smarter in Seconds', {
      y: top + h * 0.28,
      size: u * 9.5,
      at: 0
    });

    s.box('https://tripmate-ai.embarko.app', {
      id: 'link',
      y: top + h * 0.54,
      w: w * 0.76,
      h: h * 0.18,
      icon: 'globe',
      color: 'accent',
      size: u * 5.0,
      at: 'live'
    });

    s.text('Guardrails · Parallel Agents · Budget · HITL · Live Now', {
      y: top + h * 0.78,
      size: u * 3.8,
      color: 'muted',
      at: 'dot#1'
    });

    s.burst({ x: s.cx, y: top + h * 0.54, at: 'live', count: 40 });
  }
};
