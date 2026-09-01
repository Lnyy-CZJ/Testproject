/**
 * 连贯对话生成器使用的共享双人消息片段。
 *
 * 每个 beat 固定由对方先发言、自己直接回应。bank 内的顺序也经过编排，连续取用时会
 * 像同一场长聊天逐步推进，而不是把互不相关的模板句随机拼接在一起。这里仅保存中性
 * 或阶段安全的 filler；真正决定关系阶段的证据仍由场景目录提供。
 */

/**
 * 冻结 bank 及其中的 beat，防止生成流程意外改写共享文案并影响后续案例。
 *
 * @param {Array<{other: string, self: string}>} beats 已按对话顺序编排的消息片段。
 * @returns {ReadonlyArray<Readonly<{other: string, self: string}>>} 不可变的消息片段列表。
 */
function freezeBank(beats) {
  return Object.freeze(beats.map((beat) => Object.freeze(beat)));
}

const GENERAL_BEATS = freezeBank([
  // 1-7：从当天状态自然进入工作节奏。
  { other: "How has your morning been so far?", self: "Calm enough. I made tea and started with the easiest task." },
  { other: "Did starting small make the rest feel more manageable?", self: "Yes, it gave me enough momentum to open the harder file." },
  { other: "What made that file difficult to begin?", self: "It needed careful reading, and I did not want to rush the details." },
  { other: "Were you able to give it the attention it needed?", self: "I was. I turned off alerts and worked through one section at a time." },
  { other: "That sounds focused. Did you find the part that was holding you up?", self: "I did, and the problem was smaller once I wrote it down clearly." },
  { other: "Do you usually think better after writing things out?", self: "Usually. A short list keeps several thoughts from competing at once." },
  { other: "What is left on the list now?", self: "One reply, a quick review, and then I can take a proper break." },

  // 8-14：从休息聊到附近环境，保持低压力的日常交流。
  { other: "What would make the break feel useful instead of rushed?", self: "A walk around the block and a few minutes away from a screen." },
  { other: "Is the weather good enough for that today?", self: "It is cool but dry, so a light jacket should be enough." },
  { other: "Do you have a usual route when you need some air?", self: "I take the quieter street and loop past the small community garden." },
  { other: "Has anything new appeared in the garden lately?", self: "There are fresh herbs near the gate and a row of bright yellow flowers." },
  { other: "That sounds worth slowing down for. Do you ever take photos there?", self: "Sometimes, but today I would rather notice it without using my phone." },
  { other: "I understand that. What else helps you feel present?", self: "Listening for ordinary sounds instead of filling every quiet moment." },
  { other: "What sound do you notice most on that route?", self: "Usually birds near the trees and bicycles passing on the next street." },

  // 15-21：由散步转到阅读和学习，前后话题相互承接。
  { other: "Does the walk ever give you ideas for what to read next?", self: "It does. The garden made me curious about a short book on urban plants." },
  { other: "Have you found a book that looks approachable?", self: "I found one with clear drawings and chapters that can stand alone." },
  { other: "That format sounds easy to return to. Which chapter will you try first?", self: "The one about plants that grow well in shaded corners." },
  { other: "Is shade a problem where you live?", self: "Most of the windows get indirect light, so practical advice would help." },
  { other: "Would you want to grow something simple there?", self: "Maybe mint or parsley, as long as I can care for it consistently." },
  { other: "What would make the care routine realistic?", self: "One watering day, a visible spot, and a note until the habit sticks." },
  { other: "You make small systems sound comforting. Do they help in other areas too?", self: "Yes, especially with meals when the week gets busy." },

  // 22-28：从习惯过渡到做饭，所有回答都紧接问题。
  { other: "What meal works best when you do not want many decisions?", self: "A simple soup with bread because I can adjust it to what I have." },
  { other: "What would you put in the soup today?", self: "Carrots, beans, and the last of the greens in the refrigerator." },
  { other: "Would you add anything for more flavor?", self: "A little garlic, black pepper, and lemon at the end." },
  { other: "Lemon at the end sounds fresh. Did someone teach you that?", self: "I learned it from trial and error after making several flat soups." },
  { other: "What was the funniest failed version?", self: "One had far too much pepper, and every spoonful surprised me again." },
  { other: "Did you manage to rescue it?", self: "Mostly. More broth helped, and I wrote down the better amount afterward." },
  { other: "Would you make the improved version again this week?", self: "Yes, it is easy enough for tomorrow and leaves useful leftovers." },

  // 29-35：从剩饭转入周内安排和群体活动，不暗示约会或身份。
  { other: "Do leftovers make your next day easier?", self: "They do, especially when I have an evening class after work." },
  { other: "What are you learning in the class right now?", self: "We are practicing how to explain complex ideas in plain language." },
  { other: "That seems useful. What exercise did you enjoy most?", self: "We described a familiar process without using any specialist terms." },
  { other: "Which process did you choose?", self: "I explained how to organize a shared shelf so everyone can find things." },
  { other: "Did the group understand your explanation?", self: "Yes, though they suggested adding labels at eye level." },
  { other: "Was that feedback helpful?", self: "Very. It was specific, kind, and easy to use right away." },
  { other: "Will the class meet again soon?", self: "Next week, and we will each bring a revised example." },

  // 36-42：从课堂作业延伸到沟通习惯和个人边界。
  { other: "Do you already know what you want to revise?", self: "I want a clearer opening and one example that feels less abstract." },
  { other: "Would saying it aloud help you test the opening?", self: "Yes, hearing the rhythm usually reveals where a sentence is too long." },
  { other: "Do you prefer feedback immediately or after you finish?", self: "After I finish once, so I can hear the whole idea before adjusting it." },
  { other: "That is helpful to know. Do you use the same approach in conversation?", self: "Often. I listen first, then ask whether someone wants ideas or just space." },
  { other: "What helps you tell the difference?", self: "I try not to guess. A direct question is usually kinder and more accurate." },
  { other: "Does it feel easy for you to ask that directly?", self: "Easier than it used to, especially when the tone stays calm." },
  { other: "What makes a calm tone easier to maintain?", self: "Taking a breath and describing the specific moment instead of making a broad claim." },

  // 43-49：由沟通方式自然转入休息和周末安排。
  { other: "Do you have a way to reset after a demanding conversation?", self: "I wash a few dishes, stretch, and let my thoughts settle before doing more." },
  { other: "Why dishes rather than another task?", self: "The result is visible, and the warm water gives me something simple to focus on." },
  { other: "That makes sense. What do you do once your mind feels quieter?", self: "I decide whether I have energy for reading or need an early night." },
  { other: "Which one sounds right for tonight?", self: "An early night, though I may read one short chapter first." },
  { other: "Would that be the plant book you found?", self: "Probably, since a single chapter will not turn into a long commitment." },
  { other: "Do you have much planned for the weekend?", self: "Only errands and a group lunch, so there is room to rest." },
  { other: "Are you looking forward to the group lunch?", self: "Yes, it has been a while since everyone had the same afternoon free." },

  // 50-56：以具体但开放的后续话题收尾，方便连接下一段内容。
  { other: "Is there anything you want to bring to the lunch?", self: "I may bring bread from the bakery near the bus stop." },
  { other: "Do they make the kind with seeds on top?", self: "They do, and it stays fresh long enough to share later." },
  { other: "That sounds like an easy contribution. Will you decide that morning?", self: "Yes, I will check my energy and keep the plan flexible." },
  { other: "I like that approach. What would a restful weekend feel like to you?", self: "Enough sleep, one good conversation, and no need to hurry between places." },
  { other: "Which part matters most this week?", self: "The slower pace. I have been moving quickly and want to notice more." },
  { other: "I hope you get that slower pace. Would you tell me how the garden looks later?", self: "I would be happy to share what changed after my next walk." },
  { other: "Good, I am curious whether those yellow flowers keep opening.", self: "I will look for them and let you know what I notice." },
]);

const RELATIONSHIP_BEATS = freezeBank([
  // 1-7：已确立伴侣从共同早晨和家务安排开始交流。
  { other: "Did you sleep well after we turned the lights out early?", self: "I did, and waking up without rushing made the morning gentler." },
  { other: "Would you like to keep the same bedtime tonight?", self: "Yes, if we finish the kitchen cleanup before we get tired." },
  { other: "I can wash the dishes if you clear the counter.", self: "That split works, and I will put the leftovers away too." },
  { other: "Could you label the container for tomorrow?", self: "Of course, and I will leave it on the front shelf where we can see it." },
  { other: "Thank you. Do we need anything else for breakfast?", self: "We have enough fruit, but we are nearly out of oats." },
  { other: "I can add oats to our shared list.", self: "Please do, and I will check whether we need more tea." },
  { other: "The tea is still fine. How is your energy for work today?", self: "Better than yesterday, though I need a quiet hour before my first call." },

  // 8-14：伴侣互相支持工作，同时尊重专注边界。
  { other: "Would it help if I used the other room during that hour?", self: "Yes, thank you. I will let you know as soon as the call ends." },
  { other: "Do you want encouragement before it starts or space to focus?", self: "A quick good-luck message would feel nice, then space until I finish." },
  { other: "I can do that. What is the hardest part of the call?", self: "Explaining the delay clearly without sounding defensive." },
  { other: "Could you lead with what changed and what you can do next?", self: "That would keep it practical. I will write those two points down." },
  { other: "Would you like me to listen to the opening once?", self: "Yes, after lunch, when I have shaped it into a complete thought." },
  { other: "That timing works for me. I have a deadline before lunch too.", self: "I will keep the common room quiet so we can both concentrate." },
  { other: "I appreciate that. Shall we take a short break together at noon?", self: "Yes, ten minutes by the window would help both of us reset." },

  // 15-21：从工作休息转到共同用餐和居家节奏。
  { other: "Would you rather have soup or sandwiches for lunch?", self: "Soup sounds better, and I can warm it while you finish your note." },
  { other: "Could we add the bread left from yesterday?", self: "Yes, I will toast it so it does not go to waste." },
  { other: "I like how we have been using what we already have.", self: "Me too. It saves money and makes the kitchen easier to manage." },
  { other: "Should we review the food budget this evening?", self: "That would be useful, as long as we keep it to twenty minutes." },
  { other: "Twenty minutes is enough. What should we look at first?", self: "The recent grocery totals, then one change we both can maintain." },
  { other: "I would rather adjust snacks than cut the meals we enjoy.", self: "I agree. A plan has to support us, not make every meal stressful." },
  { other: "Could we each choose one favorite snack for the week?", self: "Yes, that feels fair and still keeps the list simple." },

  // 22-28：从预算自然过渡到共同日历和家庭社交。
  { other: "Could we also open the calendar and check the weekend?", self: "Yes, I see the family lunch and the repair appointment." },
  { other: "Do you still have energy for the family lunch?", self: "I do, but I would like us to leave before the evening gets too full." },
  { other: "What departure time would feel comfortable?", self: "Around four, with a little flexibility if the conversation is winding down." },
  { other: "I can support that. Would you like me to mention our timing early?", self: "Please, so leaving does not feel sudden or personal." },
  { other: "I will say we already have a quiet evening planned.", self: "Thank you. That is true and gives us a clear boundary." },
  { other: "Should our quiet evening include the film we saved?", self: "Yes, if we are both awake enough to enjoy it." },
  { other: "And if we are tired, we can move it without disappointment.", self: "Exactly. Time together matters more than forcing a schedule." },

  // 29-35：讨论共同空间和分工，体现健康伴侣日常。
  { other: "The repair appointment may interrupt the morning. Who can be home?", self: "I can cover the first hour if you take over after your call." },
  { other: "That handoff works. Could you write down what the repair needs?", self: "I will list the loose handle and the noise near the window." },
  { other: "Please add that the noise is worse when the wind picks up.", self: "Added. I will also ask for an estimate before any extra work." },
  { other: "Thank you for remembering the estimate.", self: "We agreed to discuss unexpected costs, so I want to keep that promise." },
  { other: "I feel better when we make those choices together.", self: "So do I. Shared decisions keep either of us from carrying too much." },
  { other: "Is there any household task you have been carrying alone?", self: "I have handled most of the laundry lately and could use a hand." },
  { other: "I can take the next two loads and fold them tonight.", self: "That would help, and I can sort everything before you start." },

  // 36-42：从分工进入小摩擦修复，不升级为关系危机。
  { other: "I also want to check in about yesterday when I sounded impatient.", self: "I noticed it, and I appreciate you bringing it up without waiting." },
  { other: "I was stressed, but the sharp tone was still mine to own.", self: "Thank you. The tone hurt, even though I understood the pressure." },
  { other: "What would have felt more respectful in that moment?", self: "Saying you needed ten quiet minutes instead of answering abruptly." },
  { other: "I can do that next time and return when I am calmer.", self: "That would help me trust that the conversation is paused, not avoided." },
  { other: "Would you be willing to remind me with a simple phrase?", self: "Yes, I can ask whether you need space rather than matching the tension." },
  { other: "I do not want that reminder to become your responsibility.", self: "I know. I can offer it, while you remain responsible for your tone." },
  { other: "That distinction feels fair to me.", self: "It feels fair to me too, and I am glad we repaired it directly." },

  // 43-49：回到亲密、感谢和共同休息。
  { other: "Do you want a hug now, or would space feel better?", self: "A hug would feel good now that we have finished talking." },
  { other: "Come here. I am grateful we can be honest and still stay gentle.", self: "I am grateful for that too. It makes our home feel safe." },
  { other: "What would help the rest of the evening feel easy?", self: "Finishing the small chores, then sitting together without another agenda." },
  { other: "I can fold the laundry while you make the tea.", self: "Deal, and I will bring both cups to the couch." },
  { other: "Would you like music or quiet while we sit?", self: "Quiet first, then something soft if we both want it." },
  { other: "I like that we can choose instead of filling every silence.", self: "Me too. Comfortable silence is one of my favorite parts of us." },
  { other: "That is one of my favorite parts too.", self: "I am glad we built a relationship where quiet can feel connected." },

  // 50-56：以共同计划和稳定承诺收尾，不暗示异地或排他讨论。
  { other: "Before we settle in, is there anything tomorrow needs from us?", self: "Only the grocery stop and a reminder about the repair window." },
  { other: "I can handle the grocery stop on my way back.", self: "Thank you. I will update the list before you leave." },
  { other: "Could you add the bread you liked last week?", self: "I will, and I will note the smaller loaf so none is wasted." },
  { other: "You always remember the practical detail.", self: "And you often remember how the plan will feel for both of us." },
  { other: "That sounds like a good team to me.", self: "It does to me too, especially when we keep checking our assumptions." },
  { other: "I love the ordinary care we give our life together.", self: "I love it too. The ordinary parts are where trust becomes visible." },
  { other: "Then let us finish the dishes and enjoy our quiet evening.", self: "Yes, I am ready for a simple evening with you." },
]);

const LONG_DISTANCE_BEATS = freezeBank([
  // 1-7：明确时差和远程交流环境，不暗示已经同城。
  { other: "Is this still a good time to talk across the time difference?", self: "Yes, it is early here, but I am awake and glad we planned it." },
  { other: "Did you have enough time to settle before the call?", self: "I did. I made breakfast and moved to the quiet side of the room." },
  { other: "Can you hear me clearly from there?", self: "Yes, your voice is clear, and the connection sounds steady today." },
  { other: "Good. Would you rather keep the camera on or save bandwidth?", self: "Let us start with video and switch to audio if the connection becomes unstable." },
  { other: "That works. How does the morning light look where you are?", self: "It is pale and cloudy, while your window still looks dark." },
  { other: "Sunset is nearly over here, so our days are crossing again.", self: "I like noticing that difference even when the distance feels hard." },
  { other: "Does the distance feel heavier today?", self: "A little, but having a reliable call gives the day a clear point of connection." },

  // 8-14：讨论远程节奏和低带宽替代方案。
  { other: "Would shorter messages help on the days our schedules do not overlap?", self: "Yes, a brief update is enough when a live conversation is not possible." },
  { other: "What kind of update feels connecting without creating pressure?", self: "One real detail about the day and no expectation of an immediate reply." },
  { other: "I can do that. Should we mark urgent messages more clearly?", self: "Please start with the practical need so I know it cannot wait." },
  { other: "And everything else can wait until the next shared window.", self: "Exactly. The time difference should not keep either of us on alert." },
  { other: "Would a voice note work when typing feels too flat?", self: "Yes, especially when tone matters and our awake hours barely overlap." },
  { other: "I will keep them short enough to hear during a break.", self: "Thank you, and I will tell you when I need more time to respond." },
  { other: "That honesty makes remote communication much easier.", self: "It does. Clear expectations keep silence from turning into worry." },

  // 15-21：以远程共享活动维持关系，不伪装为同城见面。
  { other: "On a lighter note, do you still want to read the next chapter together this week?", self: "Yes, we can read separately and compare notes on our weekend call." },
  { other: "How far should we read so neither of us gets ahead?", self: "Let us stop at the end of the third section and leave the rest unopened." },
  { other: "Agreed. Do you want to share questions before the call?", self: "I will write mine down and send only the headings so nothing is spoiled." },
  { other: "That will give us something specific to discuss across the miles.", self: "And it makes the call feel shared rather than like two reports." },
  { other: "Could we cook the same simple meal during another call?", self: "Yes, if we choose ingredients available in both places." },
  { other: "A vegetable soup might be easiest in both kitchens.", self: "That works, and we can compare how each version turns out." },
  { other: "I like finding small routines that survive the distance.", self: "Me too. They give our relationship texture between visits." },

  // 22-28：讨论下一次未来探访，始终保持尚未同城。
  { other: "Have you had a chance to check the travel window we discussed?", self: "I checked it, but I need to confirm my leave before we choose anything." },
  { other: "No rush. Which part of the window looks most realistic?", self: "The middle week looks possible because work is quieter then." },
  { other: "Would you prefer that I travel this time?", self: "Yes, since your schedule is more flexible and I traveled on the last visit." },
  { other: "That feels balanced. I will compare routes without booking yet.", self: "Thank you. Please wait until my leave is approved before paying." },
  { other: "I will only note flexible options for now.", self: "That lowers the pressure and protects us if the dates have to change." },
  { other: "When we confirm, should we leave the first evening unplanned?", self: "Yes, travel can be tiring, and quiet time together would be enough." },
  { other: "I am looking forward to being in the same room again.", self: "So am I, while remembering we still have weeks of distance first." },

  // 29-35：处理探访成本与时差带来的实际负担。
  { other: "Should we review the travel budget before choosing a route?", self: "Yes, I want the visit to feel sustainable for both of us." },
  { other: "I can cover the travel if we split the local costs.", self: "That could work, but let us write down the estimate before deciding." },
  { other: "I will include transport, food, and one flexible activity.", self: "Please leave room for rest so we do not spend just to fill time." },
  { other: "Agreed. The point is being together, not a packed schedule.", self: "Exactly, especially after the effort it takes to cross the distance." },
  { other: "Is there any remote expense we should adjust this month?", self: "We could skip sending packages and put that money toward the visit." },
  { other: "A thoughtful message is enough for me in the meantime.", self: "For me too. I do not need an object to feel remembered." },
  { other: "That helps me keep our plans within reach.", self: "It helps me too, and it keeps care from becoming a financial test." },

  // 36-42：讨论异地中的情绪需求和冲突修复。
  { other: "There is another thing I want to revisit: our call ended abruptly yesterday.", self: "I do too. I felt confused because the connection failed after your short reply." },
  { other: "The call failed, but my reply was also sharper than I intended.", self: "Thank you for separating the technical problem from the tone." },
  { other: "What would help if that happens again across the distance?", self: "A short message saying the call dropped and when we can reconnect." },
  { other: "I can send that as soon as service returns.", self: "And I will wait for that message instead of assuming the worst." },
  { other: "Would it help to have a backup audio-only time?", self: "Yes, but only if we both have energy and it does not disrupt sleep." },
  { other: "Sleep should take priority when our clocks are far apart.", self: "I agree. Exhaustion makes a small misunderstanding harder to repair." },
  { other: "I am glad we can adjust the system without blaming each other.", self: "Me too. Distance needs more planning, not more suspicion." },

  // 43-49：保持与各自本地生活的平衡。
  { other: "Do you have enough room for local friends this weekend?", self: "Yes, I kept one afternoon open for them and one window for our call." },
  { other: "That balance matters to me. I do not want distance to shrink your life.", self: "I feel the same about your life there and the people who support you." },
  { other: "Would you like a brief message before I go to the group dinner?", self: "Only if it is easy. Enjoy the dinner without managing my feelings remotely." },
  { other: "Thank you. I will send a note when I am home and awake.", self: "That is enough, and I may read it after you are asleep." },
  { other: "Our replies may cross overnight again.", self: "They probably will, but the delay does not make the care less real." },
  { other: "What helps you remember that when waiting feels long?", self: "Looking at our agreed schedule instead of measuring every quiet hour." },
  { other: "I will keep the schedule updated when work changes.", self: "Thank you. Predictability gives us room to live fully in both places." },

  // 50-56：以明确的远程后续计划收尾。
  { other: "Before we end, which call window works after the clocks change?", self: "The later window still works for me, but it will be one hour earlier here." },
  { other: "I will update the calendar so neither of us calculates it from memory.", self: "Good idea. Time changes are easy to miss when we are in different zones." },
  { other: "Should we keep the next call shorter because it is a work night?", self: "Yes, forty minutes gives us connection without sacrificing rest." },
  { other: "Is there one topic you want to save for that call?", self: "I want to hear how your class project develops after the review." },
  { other: "I will make a note so I remember to tell you.", self: "And I will bring the travel update if my leave request moves forward." },
  { other: "Then we each have something concrete for the next remote check-in.", self: "Yes, and no pressure to fill every day before then." },
  { other: "Take care of your morning while I get ready for sleep.", self: "Sleep well there. I will carry on here and talk with you soon." },
]);

const PAUSE_BEATS = freezeBank([
  // 1-7：确认暂停目的和边界，明确尚未结束关系。
  { other: "Can we confirm what this pause is meant to give us?", self: "It is time to think clearly without continuing the same conflict." },
  { other: "And it is not a final decision about the relationship today.", self: "Correct. We are pausing contact, not deciding the outcome yet." },
  { other: "When should the pause begin so the boundary is unambiguous?", self: "It should begin after this conversation and the essential details are settled." },
  { other: "How long should we leave before the first review?", self: "Two weeks feels long enough to reflect without making the pause indefinite." },
  { other: "Would a review after two weeks mean we must decide then?", self: "No, it means we check whether we need more time or can talk calmly." },
  { other: "I appreciate that distinction. How should we record the review time?", self: "We can put one neutral reminder on our calendars and leave it there." },
  { other: "Once it is recorded, I will not send reminders during the pause.", self: "Thank you. One agreed reminder is enough and protects the quiet." },

  // 8-14：细化暂停期间的联系规则，不用日常闲聊破坏边界。
  { other: "Should ordinary updates wait until the review conversation?", self: "Yes, casual updates would blur the no-contact space we are creating." },
  { other: "What about messages that only say I am thinking of you?", self: "Those should wait too, because they still ask the other person to respond emotionally." },
  { other: "I understand. Should we mute the existing chat rather than delete it?", self: "Muting is enough for me, and it avoids making a dramatic gesture." },
  { other: "Would seeing read status create pressure during the pause?", self: "It might, so I will not open nonessential messages if one arrives by mistake." },
  { other: "If I send something accidentally, I will not follow it with explanations.", self: "That helps. We can let an accidental message sit without restarting contact." },
  { other: "Should reactions and shared links count as contact too?", self: "Yes, any direct contact should wait unless it fits an agreed exception." },
  { other: "Then I will avoid every casual channel until the review.", self: "I will do the same so the boundary applies equally to both of us." },

  // 15-21：约定紧急和必要事务的窄通道。
  { other: "What situations should count as a genuine exception?", self: "A safety emergency or a time-sensitive shared obligation, nothing broader." },
  { other: "How should an urgent message begin so it is easy to recognize?", self: "Start with the practical reason and the deadline, without emotional discussion." },
  { other: "Could an urgent message stay to one question when possible?", self: "Yes, one clear question will reduce the chance of reopening the conflict." },
  { other: "If no answer is needed, I will say that directly.", self: "Please do. Knowing the expected action will keep the contact contained." },
  { other: "What response time is reasonable for a shared obligation?", self: "Within one day unless the message states an earlier unavoidable deadline." },
  { other: "And a safety emergency can use the fastest available route.", self: "Yes, safety comes before the pause, but ordinary worry does not become an emergency." },
  { other: "That limit feels clear enough for me to follow.", self: "It feels clear to me too, which makes the pause more respectful." },

  // 22-28：处理暂停期间不可避免的共同事务。
  { other: "We still have one shared bill due during the pause. How should we handle it?", self: "I will pay my usual share and send only the payment confirmation." },
  { other: "Should I acknowledge the confirmation or leave it unanswered?", self: "A brief received message is fine because it closes the practical task." },
  { other: "There is also a delivery addressed to you at my place.", self: "Please leave it with the building desk, and I will collect it without meeting." },
  { other: "I can do that and send the collection window only once.", self: "Thank you. I will not use the pickup as a reason to start a conversation." },
  { other: "Do we need to exchange any keys during the pause?", self: "No, we can leave the keys untouched until the review unless access becomes necessary." },
  { other: "That avoids turning a temporary boundary into a final gesture.", self: "Exactly. We should not make irreversible choices while we are still reflecting." },
  { other: "I will keep practical contact limited to what we named.", self: "And I will not add personal questions to those practical messages." },

  // 29-35：处理共同朋友、活动和公开场合。
  { other: "What should we tell mutual friends if they ask about us?", self: "We can say we are taking private space and do not want messages carried between us." },
  { other: "Should we ask them not to give either of us updates?", self: "Yes, indirect updates would undermine the pause even without direct contact." },
  { other: "There is a group event before our review date. Do you plan to attend?", self: "I will skip this one so neither of us has to manage an unexpected meeting." },
  { other: "Thank you. I can attend without wondering whether contact is expected.", self: "That is the goal. The pause should reduce uncertainty, not create a public test." },
  { other: "If another event appears, should the person invited first decide?", self: "Let us handle each event by practical need and avoid competing for space." },
  { other: "We can ask a neutral organizer about timing if necessary.", self: "Yes, but only for logistics and not for information about each other." },
  { other: "I will not ask friends to interpret what you are feeling.", self: "I will not do that either. Reflection needs to remain our own work." },

  // 36-42：限制线上观察和情绪性试探。
  { other: "Would checking each other's public updates violate the spirit of the pause?", self: "For me it would, because it keeps attention fixed without real consent." },
  { other: "I can hide updates temporarily instead of reading into them.", self: "I will do the same and avoid posting anything aimed at getting a reaction." },
  { other: "Should we avoid vague messages that mutual friends might relay?", self: "Yes, indirect signals can create the same pressure as direct contact." },
  { other: "I will speak to my own support people without asking them to choose sides.", self: "That is healthy, and I will keep my support conversations private too." },
  { other: "What if one of us feels a strong urge to break the pause?", self: "Write the thought privately, wait a day, and check whether it fits an exception." },
  { other: "If it does not fit, it stays unsent until the review.", self: "Yes. An intense feeling does not require immediate contact." },
  { other: "That gives us a concrete way to respect the boundary.", self: "It also gives the feeling time to become clearer before we discuss it." },

  // 43-49：明确暂停期间各自需要完成的反思工作。
  { other: "What do you hope to understand during these two weeks?", self: "I want to understand my needs without arguing against yours in my head." },
  { other: "I want to notice which concerns are patterns and which came from one hard week.", self: "That distinction could make our review more honest and specific." },
  { other: "Should we each write down what would need to change?", self: "Yes, but as personal notes, not a list of demands sent during the pause." },
  { other: "I will include what I can change, not only what I want from you.", self: "I will do the same so responsibility does not travel in one direction." },
  { other: "Would outside support be appropriate while we reflect?", self: "Yes, as long as support does not become a campaign to pressure the other person." },
  { other: "I can ask for perspective while keeping the decision ours.", self: "That feels respectful and keeps the pause focused on clarity." },
  { other: "I will not treat silence as evidence for any conclusion.", self: "Neither will I. Silence is the agreed boundary, not an answer." },

  // 50-56：安排复盘并以仍处暂停的状态收尾。
  { other: "How should we begin the review conversation when the time comes?", self: "We can each share what we learned before discussing possible next steps." },
  { other: "Would a one-hour limit help us stay grounded?", self: "Yes, and we can stop sooner if either of us becomes overwhelmed." },
  { other: "If we need more reflection afterward, can the pause continue?", self: "It can, but we should agree on a new review point rather than disappear." },
  { other: "And if we are ready to discuss the relationship, we do it then, not now.", self: "Correct. This conversation only sets the pause and its boundaries." },
  { other: "Is there any boundary we have not made clear enough?", self: "No casual contact, narrow practical exceptions, and one scheduled review are clear." },
  { other: "I will respect those terms until we speak at the review.", self: "I will respect them too and use the time for honest reflection." },
  { other: "Then I will end this conversation and let the pause begin.", self: "Understood. I am stepping back now, and no decision has been made." },
]);

const BREAKUP_BEATS = freezeBank([
  // 1-7：开启是否结束关系的讨论，但不预设最终答案。
  { other: "Can we talk honestly about whether this relationship can continue?", self: "Yes, I know the question is serious, and I do not want to avoid it." },
  { other: "I am not asking for an immediate decision in the first minute.", self: "Thank you. I need enough space to explain what has brought me here." },
  { other: "Would you like to speak first while I listen?", self: "Yes. I have felt increasingly alone when our conflicts stay unresolved." },
  { other: "Which unresolved conflict has affected you most?", self: "The repeated cancellations without notice have made reliability hard to trust." },
  { other: "I hear that the pattern matters more than one canceled plan.", self: "Exactly. One change is manageable, but repetition has changed how I feel." },
  { other: "Do you believe the trust can be repaired?", self: "I do not know yet, and that uncertainty is why we need this conversation." },
  { other: "I can accept that you do not have an answer yet.", self: "I appreciate that. I want us to examine the reality before choosing an ending." },

  // 8-14：辨认双方需求和造成伤害的模式。
  { other: "What would reliability need to look like for you now?", self: "Clear notice, fewer promises, and follow-through on the plans we do make." },
  { other: "I have promised more than my capacity allowed.", self: "That honesty helps, though the impact still needs to be addressed." },
  { other: "What impact have I missed beyond disappointment?", self: "I stopped making room for plans because I expected them to disappear." },
  { other: "That sounds exhausting and unfair to you.", self: "It has been exhausting, and I also want to understand your experience." },
  { other: "I have felt pressure to agree before checking what I can manage.", self: "I did not realize agreement felt pressured, and I want to hear more." },
  { other: "I feared that saying no would be treated as lack of care.", self: "I can see how my reaction may have reinforced that fear." },
  { other: "Can we hold both harms without deciding whose pain is larger?", self: "Yes, comparing pain would distract from whether the pattern can change." },

  // 15-21：回顾尝试过的修复及其效果。
  { other: "What have we already tried to change this pattern?", self: "We used a shared calendar and agreed to confirm plans the day before." },
  { other: "The calendar helped briefly, but I stopped updating it consistently.", self: "And the missing updates brought the same uncertainty back." },
  { other: "Would another tool matter if the habit itself does not change?", self: "Probably not. The change has to be behavioral, not only organizational." },
  { other: "Have there been times when I did follow through well?", self: "Yes, and those weeks felt calmer, but the improvement did not last." },
  { other: "What made those calmer weeks different?", self: "You made fewer commitments and told me early when your energy changed." },
  { other: "That suggests a smaller promise might be more honest.", self: "It might, if the smaller promise still meets enough of both our needs." },
  { other: "And if our needs do not overlap enough, we must face that too.", self: "Yes, compatibility matters even when neither person is acting with malice." },

  // 22-28：讨论继续或结束各自意味着什么，仍不作决定。
  { other: "What would continuing the relationship require from you?", self: "I would need to risk trusting again while setting firmer boundaries." },
  { other: "What would ending it mean for you emotionally?", self: "Grief and relief could exist together, which makes the choice complicated." },
  { other: "I feel that same mixture when I imagine an ending.", self: "Hearing that makes me feel less alone, but it does not decide the question." },
  { other: "What would continuing require from me in practical terms?", self: "Honest capacity, timely updates, and steady effort over more than a few days." },
  { other: "Those are reasonable, but I need to decide whether I can sustain them.", self: "I would rather hear uncertainty than receive another promise made from fear." },
  { other: "If I cannot sustain them, ending may be the kinder choice.", self: "That may be true, but I want you to reach that answer honestly." },
  { other: "And I want your answer to be honest, not only patient with me.", self: "Agreed. Care should not require either of us to ignore a core need." },

  // 29-35：检查关系中仍然存在的价值，不以怀旧替代判断。
  { other: "Is there anything in the relationship that still feels healthy to you?", self: "Our curiosity and the way we support each other's work still feel real." },
  { other: "Those parts matter to me too.", self: "They matter, but good parts do not automatically repair the painful pattern." },
  { other: "I do not want gratitude to become a reason to stay at any cost.", self: "Neither do I. We can honor what was good while evaluating what is possible." },
  { other: "Have our recent conversations felt safer or only quieter?", self: "Quieter, but not fully safer because the main issue remained unspoken." },
  { other: "Speaking it now feels painful but more truthful.", self: "I agree. Truth gives us a chance to choose rather than drift." },
  { other: "Do you feel pressure from me to preserve the relationship?", self: "Not in this moment, and I want us to keep the discussion that way." },
  { other: "Please tell me if my fear starts turning into pressure.", self: "I will, and I will watch for the same behavior in myself." },

  // 36-42：检验修复是否现实，但不设立停联期或关系暂停。
  { other: "Could one practical change tell us whether repair is realistic?", self: "Possibly, if it is specific enough to reveal a pattern rather than create another promise." },
  { other: "Which change would give us the clearest information?", self: "Fewer commitments, honest capacity, and early notice when a plan must change." },
  { other: "Would that address enough of the hurt to matter?", self: "It would address part of it, though reliability is not our only difference." },
  { other: "What would remain unresolved even if reliability improved?", self: "Our different needs for togetherness and independent time would still need attention." },
  { other: "Can those differences be negotiated without either of us shrinking?", self: "I do not know, and that uncertainty belongs in the decision." },
  { other: "What would a workable compromise look like?", self: "Protected alone time, dependable shared plans, and no guilt around either need." },
  { other: "Does that sound possible from where you stand now?", self: "Possible, but I am not ready to call it sustainable without more honesty." },

  // 43-49：对齐不可妥协的需求，继续判断兼容性。
  { other: "Which need feels non-negotiable for you?", self: "Reliability. I cannot keep rebuilding trust after the same preventable surprise." },
  { other: "My non-negotiable need is room to say no without proving that I care.", self: "That is fair, and I can see how my reactions made honesty harder." },
  { other: "Do those two needs conflict, or could clearer expectations support both?", self: "Clearer expectations could help, but willingness matters more than wording." },
  { other: "I think willingness exists, though I am unsure whether our capacities match.", self: "I hear that distinction, and it may be the heart of this decision." },
  { other: "Can affection be real even if our capacities do not fit?", self: "Yes. Caring for each other does not guarantee a workable relationship." },
  { other: "That is difficult to admit without treating the relationship as a failure.", self: "It is, but an honest ending would not erase the care or effort we gave." },
  { other: "Are we both still considering more than one outcome?", self: "Yes. I can imagine repair, and I can also imagine that ending may be kinder." },

  // 50-56：在同一次讨论中收束，不进入 ON_A_BREAK，也不宣布最终结果。
  { other: "Would taking ten minutes to breathe help us finish this conversation calmly?", self: "Yes, a short breather is about this conversation, not a break from the relationship." },
  { other: "When we return, can we each name our current leaning without making it final?", self: "Yes. A leaning can be honest without becoming a decision tonight." },
  { other: "My leaning is that ending may be kinder if our capacities stay this different.", self: "Mine is still uncertain, though I understand why you are leaning that way." },
  { other: "Do either of us have a final answer right now?", self: "No. We are still discussing whether this relationship can continue." },
  { other: "Until we decide, should normal contact and existing plans remain unchanged?", self: "Yes, we are not taking a relationship break or changing contact rules tonight." },
  { other: "So our current commitments stay in place while the question remains open.", self: "They do, and neither of us should pretend that means the problem is solved." },
  { other: "Then we leave tonight knowing the breakup question is still open.", self: "Yes, and we will keep discussing it without inventing an answer we do not have." },
]);

const ENDED_BEATS = freezeBank([
  // 1-7：先确认关系已经结束，避免把收尾误写成复合。
  { other: "Can we confirm that the relationship has ended and this is only closure?", self: "Yes, the ending is final, and I am here only to finish things respectfully." },
  { other: "Thank you for saying that clearly. I do not want mixed signals.", self: "Neither do I. Kindness now should not be read as reopening the relationship." },
  { other: "Should we keep contact limited to the remaining practical tasks?", self: "Yes, and once those tasks are complete, ordinary contact should stop." },
  { other: "How many practical tasks are still open?", self: "Three: belongings, the last shared bill, and one account transfer." },
  { other: "Could we handle them in that order?", self: "That order works and keeps each message focused on one subject." },
  { other: "I appreciate the structure because emotions are still tender.", self: "I do too. Clear structure lets us be civil without creating false hope." },
  { other: "Then let us begin with the belongings and stay with that topic.", self: "Agreed. I have already gathered the items that are yours." },

  // 8-14：完成物品归还，不借机见面或恢复关系。
  { other: "What items did you find so I can check the list?", self: "A jacket, two books, a charger, and the small storage box." },
  { other: "That matches my list. Did you find anything fragile?", self: "Only the framed print, and I wrapped it separately to protect it." },
  { other: "Thank you. Could the boxes be left with the building desk?", self: "Yes, that avoids an unnecessary meeting and keeps the exchange simple." },
  { other: "Which collection window will you give the desk?", self: "Any time after four tomorrow, and they will hold the boxes for one day." },
  { other: "I can collect them before the desk closes.", self: "Good. I will send one confirmation after the boxes are accepted." },
  { other: "No additional message is needed after I collect them.", self: "Understood. The desk record will be enough confirmation for me." },
  { other: "Do you want your spare container returned in the same exchange?", self: "No, you may recycle it. It is not worth extending contact over." },

  // 15-21：结清费用和收据，避免品牌、账号或真实身份信息。
  { other: "Can we move to the final shared bill now?", self: "Yes, I have the statement and only need to confirm the equal split." },
  { other: "The equal split matches what we agreed before the ending.", self: "Then I will pay my half and keep the receipt with my records." },
  { other: "Could you send only the amount and confirmation number?", self: "Yes, I will omit personal notes and send the practical details once." },
  { other: "When should I expect the payment confirmation?", self: "By tomorrow evening, before the payment deadline." },
  { other: "That timing is fine. Is any other charge pending?", self: "No, the statement shows no future balance after this payment." },
  { other: "Once it is paid, neither of us owes the other money.", self: "Correct, and I will state that clearly in the final confirmation." },
  { other: "Thank you for keeping the financial ending straightforward.", self: "It is important that neither of us carries uncertainty into the future." },

  // 22-28：处理最后的共享账户转移并移除访问权限。
  { other: "What remains on the shared account transfer?", self: "Your files have been copied, and ownership needs one final acceptance." },
  { other: "I can accept the transfer this afternoon.", self: "Once you accept it, I will remove my access and save no private copies." },
  { other: "I have accepted it now. Can you see the ownership change?", self: "Yes, it now shows you as the sole owner." },
  { other: "Please remove your access when you are ready.", self: "It is removed, and I can no longer open or edit the account." },
  { other: "That closes the last shared digital responsibility.", self: "Yes, and it protects both of us from accidental future contact." },
  { other: "Did you also remove my access from your private folder?", self: "I did, and there were no shared files left inside it." },
  { other: "Good. We should each keep only our own records now.", self: "Agreed. Separation includes respecting each other's privacy." },

  // 29-35：向共同朋友说明边界，不要求选边或传话。
  { other: "How should we handle questions from mutual friends?", self: "We can say the relationship ended and ask them not to carry messages." },
  { other: "I do not want anyone pressured to choose a side.", self: "Neither do I. They can keep separate friendships without reporting back." },
  { other: "Should we attend the same group event next month?", self: "I will skip that one so the ending has time to settle without tension." },
  { other: "Thank you. I will not use the event to seek information about you.", self: "I appreciate that and will follow the same boundary elsewhere." },
  { other: "If an unavoidable public event happens later, we can stay polite and brief.", self: "Yes, courtesy is possible without reopening private contact." },
  { other: "Would a simple greeting be acceptable in that situation?", self: "A brief greeting is fine, with no expectation of a longer conversation." },
  { other: "That boundary feels respectful and final.", self: "It does to me too, and it prevents silence from becoming hostility." },

  // 36-42：处理照片和回忆，允许感恩但不重启关系。
  { other: "There are still shared photos in the old archive. What should we do?", self: "Each of us can keep personal copies and remove shared access afterward." },
  { other: "Do you want me to send a final archive before access closes?", self: "No, I already saved the few photos I wanted for my own history." },
  { other: "I will close the shared archive after saving my own copies.", self: "Thank you. No further review or discussion of the photos is needed." },
  { other: "Some memories are good even though the relationship ended.", self: "I agree, and valuing a memory does not change the final decision." },
  { other: "I do not want gratitude to sound like an invitation back.", self: "It does not. I hear it as acknowledgment, not reconciliation." },
  { other: "Then I can say I am grateful for the care we once shared.", self: "And I can receive that while continuing forward separately." },
  { other: "Thank you for letting gratitude and finality exist together.", self: "That balance makes the closure kinder without making it unclear." },

  // 43-49：核对是否仍有遗漏的实际事项。
  { other: "Before we finish, should we check for any forgotten obligations?", self: "Yes, I have a short list so we do not need another conversation later." },
  { other: "What is the first item on that final check?", self: "Mail forwarding, which is already active and needs no action from you." },
  { other: "What comes after mail forwarding?", self: "The emergency contact form, where I have already replaced your details." },
  { other: "I have replaced your details on my form as well.", self: "Good, that keeps future emergencies from crossing old boundaries." },
  { other: "Is the shared membership already canceled?", self: "Yes, it ended without a fee, and neither person has future access." },
  { other: "Then the bill, transfer, belongings, and forms are all covered.", self: "Correct. Nothing practical remains after tomorrow's payment and pickup." },
  { other: "I will not create another task as a reason to contact you.", self: "I will not either. The closure should be allowed to become complete." },

  // 50-56：健康告别，明确不复合且不保留模糊后门。
  { other: "Do we need a final boundary for contact after tomorrow?", self: "Yes, no direct contact unless a genuine legal or safety issue appears." },
  { other: "And ordinary life updates should stay private.", self: "Agreed. We no longer have a role in managing each other's daily lives." },
  { other: "I will not send holiday messages or check whether you miss me.", self: "Thank you. I will not send those messages either." },
  { other: "This goodbye is difficult, but I accept that it is final.", self: "I accept it too and will not ask you to reconsider later." },
  { other: "I hope the life ahead of you is peaceful.", self: "I hope the same for you, from a respectful distance." },
  { other: "After the last logistics are complete, I will let the contact end.", self: "So will I. There is nothing more we need to reopen." },
  { other: "Goodbye, and thank you for closing this with care.", self: "Goodbye. I will respect the ending and move forward separately." },
]);

/**
 * 六类阶段安全的共享 beat bank。调用方可按既定顺序或确定性偏移取片段，但不应改写
 * 返回的数组或对象；所有值均已冻结。
 */
const BEAT_BANKS = Object.freeze({
  general: GENERAL_BEATS,
  relationship: RELATIONSHIP_BEATS,
  long_distance: LONG_DISTANCE_BEATS,
  pause: PAUSE_BEATS,
  breakup: BREAKUP_BEATS,
  ended: ENDED_BEATS,
});

/** 16 个产品关系阶段到安全 filler bank 的显式映射。 */
const STAGE_TO_BANK = Object.freeze({
  UNCLEAR: "general",
  NEW_CONNECTION: "general",
  FRIENDS: "general",
  TALKING: "general",
  FLIRTING: "general",
  SITUATIONSHIP: "general",
  DATE_PLANNING: "general",
  DATING: "general",
  DEFINING_RELATIONSHIP: "general",
  EXCLUSIVE: "general",
  RELATIONSHIP: "relationship",
  LONG_DISTANCE: "long_distance",
  ON_A_BREAK: "pause",
  BREAKUP_DISCUSSION: "breakup",
  RECONNECTING: "general",
  ENDED: "ended",
});

/**
 * 返回指定关系阶段可安全复用的对话片段列表。
 *
 * 早期、定义关系、排他和重联阶段共用不携带关系结论的 general bank；已经确立伴侣、
 * 异地、暂停、分手讨论和结束阶段分别使用更严格的语义 bank，避免 filler 意外跨阶段。
 *
 * @param {string} stage 产品关系阶段枚举。
 * @returns {ReadonlyArray<Readonly<{other: string, self: string}>>} 对应阶段的不可变 bank。
 * @throws {RangeError} stage 不在 16 个受支持阶段中时抛出。
 */
function beatBankForStage(stage) {
  if (!Object.prototype.hasOwnProperty.call(STAGE_TO_BANK, stage)) {
    throw new RangeError(`Unknown relationship stage: ${String(stage)}`);
  }
  return BEAT_BANKS[STAGE_TO_BANK[stage]];
}

module.exports = {
  BEAT_BANKS,
  beatBankForStage,
};
