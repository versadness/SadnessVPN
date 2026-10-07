// Живой фон окна — тот же, что в Android-приложении: жидкий градиент, северное
// сияние и перламутр по кругу, переход «протекает» по шумовой маске.
// Цвета зависят от состояния VPN. Не больше 30 кадров в секунду, в половинном
// разрешении; когда окно свёрнуто, requestAnimationFrame стоит. Своё фоновое
// изображение (has-wallpaper) и «Без анимаций» (reduce-effects) отключают фон.
(function () {
  'use strict';
  const host = document.getElementById('liveBg');
  if (!host) return;
  const cv = host.querySelector('canvas');
  const g = cv.getContext('webgl', { antialias: false, alpha: false, powerPreference: 'low-power' });
  if (!g) { host.remove(); return; }

  const FS = `precision highp float;uniform vec2 R;uniform float T,E,A,B,K;uniform vec3 C0,C1,C2,C3;
float h(vec2 p){vec3 q=fract(vec3(p.xyx)*.1031);q+=dot(q,q.yzx+33.33);return fract((q.x+q.y)*q.z);}
float n(vec2 p){vec2 i=floor(p),f=fract(p);f=f*f*(3.-2.*f);return mix(mix(h(i),h(i+vec2(1,0)),f.x),mix(h(i+vec2(0,1)),h(i+1.),f.x),f.y);}
float fbm(vec2 p){float v=0.,a=.5;for(int i=0;i<4;i++){v+=a*n(p);p=p*2.03+vec2(1.7,9.2);a*=.5;}return v;}
vec3 pal(float x){x=fract(x)*4.;return x<1.?mix(C0,C1,x):x<2.?mix(C1,C2,x-1.):x<3.?mix(C2,C3,x-2.):mix(C3,C0,x-3.);}
vec3 lava(vec2 p){vec2 s=p*1.5;vec2 q=vec2(fbm(s+T*.08),fbm(s-T*.1+3.));vec2 r=vec2(fbm(s+2.2*q+vec2(1.7,9.2)+T*.13),fbm(s+2.2*q+vec2(8.3,2.8)-T*.11));
 float f=fbm(s+2.6*r);vec3 c=pal(f*1.3+length(q)*.4+T*.02);c*=.25+1.25*f*f;c+=pow(max(0.,f-.58),2.5)*3.5*mix(vec3(1),C3,.4);return c*(1.-.45*dot(p,p));}
vec3 aur(vec2 p){vec3 c=mix(vec3(.01,.015,.04),C0*.3,smoothstep(-.2,.6,p.y));c+=pal(.35)*.22*exp(-(p.y+.5)*4.);
 vec2 g=floor(p*150.);vec2 l=fract(p*150.)-.5;c+=step(.993,h(g))*h(g+3.)*smoothstep(.45,0.,length(l))*smoothstep(-.2,.3,p.y);
 for(int i=0;i<5;i++){float fi=float(i);float k=fbm(vec2(p.x*3.2+fi*3.1,T*.12+fi*1.7));float cy=.32-fi*.15+.16*(k-.5)+.04*sin(p.x*9.+T*.5+fi);
  float dy=p.y-cy;float a=dy>0.?exp(-dy*(2.8+fi*.6)):exp(dy*14.);float s=.5+.5*n(vec2(p.x*70.+fi*13.+k*8.,T*.35));
  c+=pal(fi*.21+p.x*.6+.1)*a*s*(.5+.25*E)*(1.-fi*.1);}return c*(1.-.3*dot(p,p));}
vec3 ink(vec2 p){vec2 s=p*1.7;float w=fbm(s*1.3-T*.07);float f=fbm(s+w*1.8+vec2(T*.05,-T*.04));vec3 ir=.5+.5*cos(6.283*(f*2.2+vec3(0,.33,.67))+T*.25);
 vec3 c=mix(pal(f*1.5),pal(f*1.5)*ir*1.6,.35)*smoothstep(.2,.75,f)*1.1;c+=pow(max(0.,f-.6),2.)*1.6*mix(vec3(1),C3,.5);return c*(1.-.4*dot(p,p));}
vec3 sc(float m,vec2 p){return m<.5?lava(p):(m<1.5?aur(p):ink(p));}
void main(){vec2 p=(gl_FragCoord.xy-.5*R)/R.y;vec3 c=sc(A,p);if(K>.001){float w=clamp((K-fbm(p*1.8+T*.05)*.6)/.4,0.,1.);c=mix(c,sc(B,p),w*w*(3.-2.*w));}gl_FragColor=vec4(max(c,0.),1);}`;

  const shader = (type, src) => { const s = g.createShader(type); g.shaderSource(s, src); g.compileShader(s); return s; };
  const pr = g.createProgram();
  g.attachShader(pr, shader(g.VERTEX_SHADER, 'attribute vec2 a;void main(){gl_Position=vec4(a,0,1);}'));
  g.attachShader(pr, shader(g.FRAGMENT_SHADER, FS));
  g.linkProgram(pr);
  if (!g.getProgramParameter(pr, g.LINK_STATUS)) { host.remove(); return; }
  g.useProgram(pr);
  g.bindBuffer(g.ARRAY_BUFFER, g.createBuffer());
  g.bufferData(g.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), g.STATIC_DRAW);
  const loc = g.getAttribLocation(pr, 'a');
  g.enableVertexAttribArray(loc);
  g.vertexAttribPointer(loc, 2, g.FLOAT, false, 0, 0);
  const U = k => g.getUniformLocation(pr, k);
  const u = { R: U('R'), T: U('T'), E: U('E'), A: U('A'), B: U('B'), K: U('K'), C: [0, 1, 2, 3].map(i => U('C' + i)) };

  const hex = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255);
  const PAL = {
    off: ['#2b1f6e', '#5b3bb5', '#1b3f8f', '#8a4fd0'].map(hex),
    busy: ['#8b7cff', '#ff6fb1', '#38e0b0', '#ffc25c'].map(hex),
    on: ['#0f8f7a', '#45d6a1', '#1fa2c9', '#2e5bff'].map(hex),
  };
  const state = () => {
    // ST — общее состояние из app.js (глобальная переменная скрипта, не свойство window).
    const st = (typeof ST !== 'undefined') ? ST : null;
    if (!st) return 'off';
    if (st.status === 'connecting' || st.status === 'stopping') return 'busy';
    return (st.status === 'on' || st.connected) ? 'on' : 'off';
  };
  const HOLD = 16, FADE = 5;
  let cur = PAL.off.map(c => c.slice()), energy = 0.3, T = 0, clock = 0, last = performance.now(), acc = 0, drawnStatic = false;

  const disabled = () => document.documentElement.classList.contains('has-wallpaper');
  const still = () => document.body.classList.contains('reduce-effects');

  function draw() {
    const w = Math.max(1, Math.round(innerWidth / 2)), h = Math.max(1, Math.round(innerHeight / 2));
    if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
    g.viewport(0, 0, w, h);
    const per = HOLD + FADE, a = Math.floor(clock / per) % 3, x = Math.min(1, Math.max(0, (clock % per - HOLD) / FADE));
    g.uniform2f(u.R, w, h); g.uniform1f(u.T, T); g.uniform1f(u.E, energy);
    g.uniform1f(u.A, a); g.uniform1f(u.B, (a + 1) % 3); g.uniform1f(u.K, x * x * (3 - 2 * x));
    u.C.forEach((l, i) => g.uniform3fv(l, cur[i]));
    g.drawArrays(g.TRIANGLES, 0, 3);
  }

  function frame(now) {
    requestAnimationFrame(frame);
    const dt = Math.min(0.1, (now - last) / 1000); last = now;
    host.classList.toggle('off', disabled());
    if (disabled()) return;
    if (still()) { if (!drawnStatic) { draw(); drawnStatic = true; } return; }
    drawnStatic = false;
    acc += dt;
    if (acc < 1 / 30) return;
    const step = acc; acc = 0;
    const s = state(), target = PAL[s];
    cur = cur.map((c, i) => c.map((v, j) => v + (target[i][j] - v) * Math.min(1, step * 2.5)));
    energy += ((s === 'on' ? 1 : s === 'busy' ? 1.7 : 0.3) - energy) * Math.min(1, step * 2);
    T += step * energy; clock += step;
    draw();
  }
  requestAnimationFrame(frame);
})();
