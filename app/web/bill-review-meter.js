// Active review is an estimate: visible + focused + recent input, excluding busy/idle gaps.
(() => {
  class BillReviewMeter {
    constructor({send,active,clock=()=>Date.now(),id=()=>crypto.randomUUID().replaceAll('-','')}) {
      Object.assign(this,{send,active,clock,id});this.context=null;this.pending=[];this.ms=0;this.last=this.clock();this.activityAt=-Infinity;this.sending=false;
    }
    tick(){const now=this.clock(),delta=now-this.last;
      if(this.context&&this.active()&&delta>0&&delta<=5000&&now-this.activityAt<=15000)this.ms+=delta;
      this.last=now;
    }
    activity(){this.tick();this.activityAt=this.clock();}
    select(context){this.tick();if(this.context?.id!==context?.id||this.context?.scope!==context?.scope){this.capture();this.activityAt=this.clock();}this.context=context;}
    capture(){if(this.context&&this.ms>=1){this.pending.push({context:{...this.context},body:{event_id:this.id(),revision:this.context.revision,active_ms:Math.min(60000,Math.round(this.ms))}});this.ms=0;}}
    async flush(){this.tick();this.capture();if(this.sending)return;this.sending=true;
      try{while(this.pending.length){const sample=this.pending[0];await this.send(sample);this.pending.shift();}}
      finally{this.sending=false;}
    }
  }
  if(typeof module!=='undefined')module.exports=BillReviewMeter;
  if(typeof window!=='undefined')window.BillReviewMeter=BillReviewMeter;
})();
